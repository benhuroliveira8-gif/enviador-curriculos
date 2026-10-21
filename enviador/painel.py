"""Painel visual local: abra com `python -m enviador painel` (ou abrir_painel.bat).

Roda só no seu computador (endereço 127.0.0.1), ninguém de fora acessa.
"""
from datetime import datetime
import json
import logging
import os
import threading
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, send_file

from . import aprendizado, configuracao, curriculo, entrevista, ia, raiox
from .banco import ETAPAS, ETAPAS_ATIVAS, Banco
from .candidatura import respostas_para
from .servico import ErroConfig, ErroVaga, adicionar_vaga, carregar_cv, reanalisar, rodar_busca

log = logging.getLogger(__name__)
HTML = Path(__file__).with_name("painel.html")


def _lista(valor) -> list:
    try:
        return json.loads(valor or "[]")
    except (TypeError, ValueError):
        return []


def _vaga_json(r) -> dict:
    return {
        "id": r["id"], "titulo": r["titulo"], "empresa": r["empresa"] or "", "url": r["url"] or "",
        "cidade": r["cidade"] or "", "remoto": bool(r["remoto"]), "fonte": r["fonte"],
        "manual": (r["fonte"] or "").startswith("manual"),
        "nota": r["nota"], "status": r["status"], "metodo": r["metodo"] or "palavras",
        "resumo": (r["analise"] or "").split(" | ")[0],
        "pontos_fortes": _lista(r["pontos_fortes"]), "lacunas": _lista(r["lacunas"]),
        "email": (r["emails"] or "").split(",")[0], "encontrada_em": r["encontrada_em"],
        "etapa": r["etapa"], "etapa_em": r["etapa_em"], "tem_respostas": bool(r["respostas"]),
        "tem_preparo": bool(r["preparo"]),
    }


def _texto_lista(v) -> list[str]:
    if isinstance(v, list):
        itens = v
    else:
        itens = str(v or "").replace("\n", ",").split(",")
    return [s.strip() for s in itens if str(s).strip()]


def _config_publica(cfg: dict) -> dict:
    """O que o painel mostra na tela de configurações (sem senha nem chave)."""
    b, an, av, sm = cfg["busca"], cfg["analise"], cfg["aviso"], cfg["smtp"]
    chave = cfg["ia"]["chave_api"] or os.getenv("ANTHROPIC_API_KEY", "")
    return {
        "candidato": {k: cfg["candidato"][k] for k in ("nome", "email", "telefone", "linkedin",
                                                         "pretensao_salarial", "resumo")},
        "busca": {"palavras_chave": b["palavras_chave"], "palavras_excluidas": b["palavras_excluidas"],
                  "cidades": b["cidades"], "aceitar_remoto": b["aceitar_remoto"], "dias_maximos": b["dias_maximos"],
                  "fontes": dict(b["fontes"]), "adzuna_app_id": b["adzuna"]["app_id"],
                  "adzuna_tem_chave": bool(b["adzuna"]["app_key"]), "adzuna_onde": b["adzuna"]["onde"]},
        "analise": {"nota_minima": an["nota_minima"]},
        "ia": {"configurada": bool(chave), "final": chave[-4:] if chave else "",
               "pelo_ambiente": bool(os.getenv("ANTHROPIC_API_KEY")) and not cfg["ia"]["chave_api"]},
        "aviso": {"email": av["email"], "nota_alerta": av["nota_alerta"]},
        "acompanhamento": {"dias_followup": cfg["acompanhamento"]["dias_followup"]},
        "smtp": {"usuario": sm["usuario"], "servidor": sm["servidor"], "porta": sm["porta"],
                 "tem_senha": bool(sm["senha"])},
    }


def _inteiro(valor, minimo, maximo, nome):
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise ValueError(f"{nome}: digite um número.")
    if not minimo <= n <= maximo:
        raise ValueError(f"{nome}: use um valor entre {minimo} e {maximo}.")
    return n


def aplicar_alteracoes(cfg: dict, d: dict) -> dict:
    """Aplica no config o que veio do formulário. Campos de senha vazios mantêm o valor atual."""
    ca, b, sm = cfg["candidato"], cfg["busca"], cfg["smtp"]
    if "candidato" in d:
        for k in ("nome", "email", "telefone", "linkedin", "pretensao_salarial", "resumo"):
            if k in d["candidato"]:
                ca[k] = str(d["candidato"][k] or "").strip()
    if "busca" in d:
        x = d["busca"]
        for k in ("palavras_chave", "palavras_excluidas", "cidades"):
            if k in x:
                b[k] = _texto_lista(x[k])
        if "aceitar_remoto" in x:
            b["aceitar_remoto"] = bool(x["aceitar_remoto"])
        if "dias_maximos" in x:
            b["dias_maximos"] = _inteiro(x["dias_maximos"], 1, 90, "Dias máximos")
        for f in ("gupy", "adzuna", "github_vagas"):
            if f in x.get("fontes", {}):
                b["fontes"][f] = bool(x["fontes"][f])
        if "adzuna_app_id" in x:
            b["adzuna"]["app_id"] = str(x["adzuna_app_id"] or "").strip()
        if x.get("adzuna_app_key"):
            b["adzuna"]["app_key"] = str(x["adzuna_app_key"]).strip()
        if "adzuna_onde" in x:
            b["adzuna"]["onde"] = str(x["adzuna_onde"] or "").strip()
        if b["fontes"]["adzuna"] and not (b["adzuna"]["app_id"] and b["adzuna"]["app_key"]):
            raise ValueError("Para usar a Adzuna, preencha o app_id e o app_key.")
        if not b["palavras_chave"]:
            raise ValueError("Informe pelo menos um cargo para buscar.")
    if "analise" in d and "nota_minima" in d["analise"]:
        cfg["analise"]["nota_minima"] = _inteiro(d["analise"]["nota_minima"], 30, 95, "Nota mínima")
    if "aviso" in d:
        if "nota_alerta" in d["aviso"]:
            cfg["aviso"]["nota_alerta"] = _inteiro(d["aviso"]["nota_alerta"], 30, 100, "Nota para destaque")
        if "email" in d["aviso"]:
            cfg["aviso"]["email"] = bool(d["aviso"]["email"])
    if "acompanhamento" in d and "dias_followup" in d["acompanhamento"]:
        cfg["acompanhamento"]["dias_followup"] = _inteiro(d["acompanhamento"]["dias_followup"], 3, 60, "Dias para follow-up")
    if "smtp" in d:
        x = d["smtp"]
        if "usuario" in x:
            sm["usuario"] = str(x["usuario"] or "").strip()
            auto = configuracao.servidor_smtp(sm["usuario"])
            if auto:
                sm["servidor"], sm["porta"] = auto
        if x.get("servidor"):
            sm["servidor"] = str(x["servidor"]).strip()
        if x.get("porta"):
            sm["porta"] = _inteiro(x["porta"], 1, 65535, "Porta")
        if x.get("senha"):
            sm["senha"] = str(x["senha"]).strip()
    if "ia" in d and d["ia"].get("chave_api"):
        cfg["ia"]["chave_api"] = str(d["ia"]["chave_api"]).strip()
        os.environ["ANTHROPIC_API_KEY"] = cfg["ia"]["chave_api"]
    return cfg


def criar_app(config: dict, caminho_banco: str = "historico.db", cv: str | None = None,
              caminho_config: str | None = None) -> Flask:
    app = Flask(__name__)
    config.update(configuracao.completar(config))
    estado = {"cv": cv, "tarefa": {"rodando": False, "tipo": "", "mensagem": "", "terminou_em": None}}
    trava = threading.Lock()

    def banco() -> Banco:
        return Banco(caminho_banco)

    def obter_cv() -> str:
        if estado["cv"] is None:
            estado["cv"] = carregar_cv(config)
        return estado["cv"]

    def erro(msg, codigo=400):
        return jsonify({"erro": msg}), codigo

    def vaga_ou_404(b, id):
        r = b.vaga(id)
        if not r:
            raise LookupError
        return r

    @app.errorhandler(LookupError)
    def _nao_achou(_):
        return erro("Vaga não encontrada.", 404)

    @app.errorhandler(ErroConfig)
    def _config(e):
        return erro(str(e), 400)

    @app.get("/")
    def inicio():
        return send_file(HTML)

    @app.get("/api/resumo")
    def resumo():
        b = banco()
        dias = config["acompanhamento"]["dias_followup"]
        fila = b.listar(("nova", "depois"))
        return jsonify({
            "fila": len(fila),
            "candidaturas": len(b.candidaturas()),
            "ativas": len(b.candidaturas(so_ativas=True)),
            "followups": len(b.followups(dias)),
            "descartadas": len(b.listar(("descartada", "baixa"))),
            "sem_ia": sum(1 for r in b.listar(("nova", "depois", "baixa")) if (r["metodo"] or "") != "ia"),
            "ia": ia.disponivel(),
            "etapas": b.contagem_etapas(),
            "nomes_etapas": ETAPAS, "etapas_ativas": ETAPAS_ATIVAS,
            "nota_minima": config["analise"]["nota_minima"],
            "dias_followup": dias,
            "tarefa": estado["tarefa"],
            "configurado": bool(config["candidato"]["nome"] and config["busca"]["palavras_chave"]),
        })

    @app.get("/api/vagas")
    def vagas():
        b = banco()
        aba = request.args.get("aba", "fila")
        texto = request.args.get("q", "").strip()
        nota_min = int(request.args.get("nota_min", 0) or 0)
        if aba == "fila":
            linhas = b.listar(("nova", "depois"), nota_min, texto)
        elif aba == "candidaturas":
            linhas = [r for r in b.candidaturas()
                      if not texto or texto.lower() in f"{r['titulo']} {r['empresa']}".lower()]
        elif aba == "followup":
            linhas = b.followups(config["acompanhamento"]["dias_followup"])
        else:
            linhas = b.listar(("descartada", "baixa"), nota_min, texto)
        return jsonify([_vaga_json(r) for r in linhas])

    @app.post("/api/vagas")
    def nova_vaga():
        d = request.json or {}
        try:
            r, nova = adicionar_vaga(config, banco(), d.get("titulo", ""), d.get("descricao", ""),
                                     d.get("empresa", ""), d.get("url", ""), d.get("cidade", ""),
                                     bool(d.get("remoto")), cv=obter_cv())
        except ErroVaga as e:
            return erro(str(e))
        return jsonify({**_vaga_json(r), "ja_existia": not nova})

    @app.get("/api/vagas/<int:id>")
    def detalhe(id):
        b = banco()
        r = vaga_ou_404(b, id)
        d = _vaga_json(r)
        d["historico"] = [{"etapa": h["etapa"], "nome": ETAPAS.get(h["etapa"], "Follow-up feito"),
                           "data": h["data"], "obs": h["obs"]} for h in b.historico_etapas(r["chave"])]
        return jsonify(d)

    @app.post("/api/vagas/<int:id>/status")
    def status(id):
        novo = (request.json or {}).get("status")
        if novo not in ("nova", "depois", "descartada", "candidatei"):
            return erro("Status inválido.")
        b = banco()
        r = vaga_ou_404(b, id)
        b.marcar(r["chave"], novo)
        return jsonify(_vaga_json(b.vaga(id)))

    @app.post("/api/vagas/<int:id>/etapa")
    def etapa(id):
        dados = request.json or {}
        nova = dados.get("etapa")
        if nova not in ETAPAS:
            return erro("Etapa inválida.")
        b = banco()
        r = vaga_ou_404(b, id)
        if r["status"] not in ("candidatei", "enviada"):
            b.marcar(r["chave"], "candidatei")
        b.registrar_etapa(r["chave"], nova, (dados.get("obs") or "").strip())
        return jsonify(_vaga_json(b.vaga(id)))

    @app.post("/api/vagas/<int:id>/followup")
    def followup(id):
        b = banco()
        r = vaga_ou_404(b, id)
        b.marcar_followup(r["chave"])
        return jsonify({"ok": True})

    @app.get("/api/vagas/<int:id>/respostas")
    def respostas(id):
        b = banco()
        r = vaga_ou_404(b, id)
        try:
            return jsonify(respostas_para(b, r, obter_cv(), config).__dict__)
        except ErroConfig:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("Falha ao preparar respostas")
            return erro(f"Não consegui preparar as respostas: {e}", 500)

    @app.get("/api/vagas/<int:id>/entrevista")
    def api_entrevista(id):
        b = banco()
        r = vaga_ou_404(b, id)
        try:
            p = entrevista.preparo_do_banco(b, r, obter_cv(), config, refazer=request.args.get("refazer") == "1")
        except ErroConfig:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("Falha no preparo de entrevista")
            return erro(f"Não consegui preparar a entrevista: {e}", 500)
        return jsonify({**p, "titulo": r["titulo"], "empresa": r["empresa"] or ""})

    def _raiox_e_area():
        vagas = banco().vagas_analisadas()
        rx = raiox.calcular(vagas, obter_cv(), config)
        area = [v for v in vagas if (v["nota"] or 0) >= config["raiox"]["nota_minima_area"]]
        return rx, area

    @app.get("/api/raiox")
    def api_raiox():
        rx, area = _raiox_e_area()
        item = lambda i: {"habilidade": i.habilidade, "percentual": i.percentual,
                          "vagas": i.vagas, "em_quase": i.em_quase}
        return jsonify({"total_area": rx.total_area, "total_quase": rx.total_quase,
                        "faltam": [item(i) for i in rx.faltam[:15]],
                        "tenho": [item(i) for i in rx.tenho[:15]],
                        "lacunas_ia": rx.lacunas_ia[:10], "usou_ia": rx.usou_ia,
                        "sugestoes": curriculo.sugestoes_regras(obter_cv(), rx, config, area)})

    @app.post("/api/curriculo/ia")
    def curriculo_ia():
        if not ia.disponivel():
            return erro("Configure a chave da Anthropic na aba Configurações.")
        rx, _ = _raiox_e_area()
        try:
            return jsonify(curriculo.sugestoes_ia(obter_cv(), rx, config))
        except Exception as e:  # noqa: BLE001
            log.exception("Falha nas sugestões de currículo")
            return erro(f"Não consegui gerar as sugestões: {e}", 500)

    @app.get("/api/resultados")
    def resultados():
        return jsonify(aprendizado.analisar(banco(), config))

    # ---------- configurações ----------
    @app.get("/api/config")
    def ver_config():
        return jsonify(_config_publica(config))

    @app.post("/api/config")
    def salvar_config():
        import copy
        novo = copy.deepcopy(config)
        try:
            aplicar_alteracoes(novo, request.json or {})
        except ValueError as e:
            return erro(str(e))
        if caminho_config:
            configuracao.salvar(novo, caminho_config)
        config.clear()
        config.update(novo)
        return jsonify(_config_publica(config))

    @app.post("/api/config/testar-ia")
    def testar_ia():
        chave = (request.json or {}).get("chave_api") or config["ia"]["chave_api"] or os.getenv("ANTHROPIC_API_KEY", "")
        ok, msg = ia.testar_chave(chave)
        return jsonify({"ok": ok, "mensagem": msg})

    @app.post("/api/config/testar-email")
    def testar_email():
        d = request.json or {}
        sm = dict(config["smtp"])
        if d.get("usuario"):
            sm["usuario"] = d["usuario"].strip()
            auto = configuracao.servidor_smtp(sm["usuario"])
            if auto:
                sm["servidor"], sm["porta"] = auto
        if d.get("senha"):
            sm["senha"] = d["senha"].strip()
        if not (sm["usuario"] and sm["senha"]):
            return jsonify({"ok": False, "mensagem": "Preencha o e-mail e a senha de app."})
        ok, msg = configuracao.testar_smtp(sm)
        return jsonify({"ok": ok, "mensagem": msg})

    # ---------- tarefas demoradas (busca e reanálise) ----------
    def em_segundo_plano(tipo: str, inicio: str, func):
        with trava:
            if estado["tarefa"]["rodando"]:
                return jsonify(estado["tarefa"])
            estado["tarefa"] = {"rodando": True, "tipo": tipo, "mensagem": inicio, "terminou_em": None}

        def rodar():
            try:
                msg = func()
            except Exception as e:  # noqa: BLE001
                log.exception("Falha em %s", tipo)
                msg = f"Não deu certo: {e}"
            estado["tarefa"] = {"rodando": False, "tipo": tipo, "mensagem": msg,
                                "terminou_em": datetime.now().isoformat(timespec="seconds")}

        threading.Thread(target=rodar, daemon=True).start()
        return jsonify(estado["tarefa"])

    @app.post("/api/buscar")
    def buscar():
        def f():
            res = rodar_busca(config, Banco(caminho_banco), obter_cv())
            return (f"{res.encontradas} vagas encontradas, {res.novas} novas, "
                    f"{len(res.recomendadas)} recomendadas.")
        return em_segundo_plano("busca", "Buscando vagas…", f)

    @app.post("/api/reanalisar")
    def api_reanalisar():
        if not ia.disponivel():
            return erro("Configure a chave da Anthropic na aba Configurações.")

        def f():
            r = reanalisar(config, Banco(caminho_banco), obter_cv())
            return (f"{r['analisadas']} vagas reanalisadas com IA, {r['recomendadas']} recomendadas, "
                    f"{r['mudaram']} mudaram de lado.")
        return em_segundo_plano("reanalise", "Reanalisando com IA…", f)

    return app


def rodar(config: dict, caminho_banco: str = "historico.db", porta: int = 8765, abrir: bool = True,
          caminho_config: str = "config.yaml"):
    app = criar_app(config, caminho_banco, caminho_config=caminho_config)
    url = f"http://127.0.0.1:{porta}"
    print(f"Painel aberto em {url}  (deixe esta janela aberta; Ctrl+C para fechar)")
    if abrir:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    app.run(host="127.0.0.1", port=porta, debug=False)
