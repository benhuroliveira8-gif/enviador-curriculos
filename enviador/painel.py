"""Painel visual local: abra com `python -m enviador painel`.

Roda só no seu computador (endereço 127.0.0.1), ninguém de fora acessa.
"""
from datetime import datetime
import json
import logging
import threading
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, send_file

from . import raiox
from .banco import ETAPAS, ETAPAS_ATIVAS, Banco
from .candidatura import respostas_para
from .servico import carregar_cv, rodar_busca

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
        "nota": r["nota"], "status": r["status"], "metodo": r["metodo"] or "palavras",
        "resumo": (r["analise"] or "").split(" | ")[0],
        "pontos_fortes": _lista(r["pontos_fortes"]), "lacunas": _lista(r["lacunas"]),
        "email": (r["emails"] or "").split(",")[0], "encontrada_em": r["encontrada_em"],
        "etapa": r["etapa"], "etapa_em": r["etapa_em"], "tem_respostas": bool(r["respostas"]),
    }


def criar_app(config: dict, caminho_banco: str = "historico.db", cv: str | None = None) -> Flask:
    app = Flask(__name__)
    estado = {"cv": cv, "busca": {"rodando": False, "mensagem": "", "terminou_em": None}}
    trava = threading.Lock()

    def banco() -> Banco:
        return Banco(caminho_banco)

    def obter_cv() -> str:
        if estado["cv"] is None:
            estado["cv"] = carregar_cv(config)
        return estado["cv"]

    @app.get("/")
    def inicio():
        return send_file(HTML)

    @app.get("/api/resumo")
    def resumo():
        b = banco()
        dias = config.get("acompanhamento", {}).get("dias_followup", 10)
        return jsonify({
            "fila": len(b.fila_candidaturas()),
            "candidaturas": len(b.candidaturas()),
            "ativas": len(b.candidaturas(so_ativas=True)),
            "followups": len(b.followups(dias)),
            "descartadas": len(b.listar(("descartada", "baixa"))),
            "etapas": b.contagem_etapas(),
            "nomes_etapas": ETAPAS, "etapas_ativas": ETAPAS_ATIVAS,
            "nota_minima": config.get("analise", {}).get("nota_minima", 65),
            "dias_followup": dias,
            "busca": estado["busca"],
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
            linhas = b.followups(config.get("acompanhamento", {}).get("dias_followup", 10))
        else:
            linhas = b.listar(("descartada", "baixa"), nota_min, texto)
        return jsonify([_vaga_json(r) for r in linhas])

    @app.get("/api/vagas/<int:id>")
    def detalhe(id):
        b = banco()
        r = b.vaga(id)
        if not r:
            return jsonify({"erro": "Vaga não encontrada."}), 404
        d = _vaga_json(r)
        d["historico"] = [{"etapa": h["etapa"], "nome": ETAPAS.get(h["etapa"], "Follow-up feito"),
                           "data": h["data"], "obs": h["obs"]} for h in b.historico_etapas(r["chave"])]
        return jsonify(d)

    @app.post("/api/vagas/<int:id>/status")
    def status(id):
        novo = (request.json or {}).get("status")
        if novo not in ("nova", "depois", "descartada", "candidatei"):
            return jsonify({"erro": "Status inválido."}), 400
        b = banco()
        r = b.vaga(id)
        if not r:
            return jsonify({"erro": "Vaga não encontrada."}), 404
        b.marcar(r["chave"], novo)
        return jsonify(_vaga_json(b.vaga(id)))

    @app.post("/api/vagas/<int:id>/etapa")
    def etapa(id):
        dados = request.json or {}
        nova = dados.get("etapa")
        if nova not in ETAPAS:
            return jsonify({"erro": "Etapa inválida."}), 400
        b = banco()
        r = b.vaga(id)
        if not r:
            return jsonify({"erro": "Vaga não encontrada."}), 404
        if r["status"] not in ("candidatei", "enviada"):
            b.marcar(r["chave"], "candidatei")
        b.registrar_etapa(r["chave"], nova, (dados.get("obs") or "").strip())
        return jsonify(_vaga_json(b.vaga(id)))

    @app.post("/api/vagas/<int:id>/followup")
    def followup(id):
        b = banco()
        r = b.vaga(id)
        if not r:
            return jsonify({"erro": "Vaga não encontrada."}), 404
        b.marcar_followup(r["chave"])
        return jsonify({"ok": True})

    @app.get("/api/vagas/<int:id>/respostas")
    def respostas(id):
        b = banco()
        r = b.vaga(id)
        if not r:
            return jsonify({"erro": "Vaga não encontrada."}), 404
        try:
            return jsonify(respostas_para(b, r, obter_cv(), config).__dict__)
        except Exception as e:
            log.exception("Falha ao preparar respostas")
            return jsonify({"erro": f"Não consegui preparar as respostas: {e}"}), 500

    @app.get("/api/raiox")
    def api_raiox():
        try:
            rx = raiox.calcular(banco().vagas_analisadas(), obter_cv(), config)
        except Exception as e:
            return jsonify({"erro": str(e)}), 500
        item = lambda i: {"habilidade": i.habilidade, "percentual": i.percentual,
                          "vagas": i.vagas, "em_quase": i.em_quase}
        return jsonify({"total_area": rx.total_area, "total_quase": rx.total_quase,
                        "faltam": [item(i) for i in rx.faltam[:15]],
                        "tenho": [item(i) for i in rx.tenho[:15]],
                        "lacunas_ia": rx.lacunas_ia[:10], "usou_ia": rx.usou_ia})

    @app.post("/api/buscar")
    def buscar():
        with trava:
            if estado["busca"]["rodando"]:
                return jsonify(estado["busca"])
            estado["busca"] = {"rodando": True, "mensagem": "Buscando vagas…", "terminou_em": None}

        def tarefa():
            try:
                res = rodar_busca(config, Banco(caminho_banco), obter_cv())
                msg = (f"{res.encontradas} vagas encontradas, {res.novas} novas, "
                       f"{len(res.recomendadas)} recomendadas.")
            except Exception as e:
                log.exception("Falha na busca pelo painel")
                msg = f"A busca falhou: {e}"
            estado["busca"] = {"rodando": False, "mensagem": msg,
                               "terminou_em": datetime.now().isoformat(timespec="seconds")}

        threading.Thread(target=tarefa, daemon=True).start()
        return jsonify(estado["busca"])

    return app


def rodar(config: dict, caminho_banco: str = "historico.db", porta: int = 8765, abrir: bool = True):
    app = criar_app(config, caminho_banco)
    url = f"http://127.0.0.1:{porta}"
    print(f"Painel aberto em {url}  (deixe esta janela aberta; Ctrl+C para fechar)")
    if abrir:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    app.run(host="127.0.0.1", port=porta, debug=False)
