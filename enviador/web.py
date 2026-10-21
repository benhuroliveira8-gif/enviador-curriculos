"""Site público: a pessoa envia o currículo e vê as vagas em que tem mais chance.

Gratuito e sem login. O currículo é lido em memória e descartado ao fim da análise;
nada é gravado em disco. O resultado fica disponível por 30 minutos e depois é apagado.

Rodar localmente:  python -m enviador site          (http://127.0.0.1:8000)
Em produção (Render): veja render.yaml. Variáveis de ambiente:
    ANTHROPIC_API_KEY          chave da IA (sem ela, o site funciona só por palavras-chave)
    MODELO_SITE                modelo usado nas análises (padrão: o rápido, mais barato)
    ANALISES_POR_PESSOA_DIA    limite por pessoa (IP) por dia, padrão 3
    ANALISES_IA_DIA            quantas análises completas com IA por dia, no total, padrão 50
    VAGAS_COM_IA               quantas vagas cada análise manda para a IA, padrão 12
    CONTATO_EMAIL              e-mail mostrado na política de privacidade
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
import io
import logging
import os
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_file

from . import fontes, ia
from .analise import analisar_com_ia, nota_rapida
from .configuracao import completar, sugerir_perfil
from .raiox import normalizar

log = logging.getLogger(__name__)
PASTA = Path(__file__).parent
VIDA_RESULTADO = 30 * 60          # segundos
VIDA_CACHE_VAGAS = 60 * 60
MAX_PDF = 5 * 1024 * 1024
NOTA_MINIMA_MOSTRAR = 50          # abaixo disso a vaga não aparece: só confundiria


def _env_int(nome: str, padrao: int) -> int:
    try:
        return int(os.getenv(nome, padrao))
    except ValueError:
        return padrao


# ---------- limites de uso ----------
class Limites:
    """Contadores em memória, zerados a cada dia (e quando o servidor reinicia)."""

    def __init__(self, por_pessoa: int, ia_por_dia: int):
        self.por_pessoa, self.ia_por_dia = por_pessoa, ia_por_dia
        self._dia, self._pessoas, self._ia = date.today(), {}, 0
        self._trava = threading.Lock()

    def _virar_dia(self):
        if date.today() != self._dia:
            self._dia, self._pessoas, self._ia = date.today(), {}, 0

    def registrar_pessoa(self, ip: str) -> bool:
        with self._trava:
            self._virar_dia()
            if self._pessoas.get(ip, 0) >= self.por_pessoa:
                return False
            self._pessoas[ip] = self._pessoas.get(ip, 0) + 1
            return True

    def reservar_ia(self) -> bool:
        with self._trava:
            self._virar_dia()
            if self._ia >= self.ia_por_dia:
                return False
            self._ia += 1
            return True


class CacheVagas:
    """Guarda por 1 hora o resultado de cada busca na Gupy, para não repetir a mesma consulta."""

    def __init__(self, vida: int = VIDA_CACHE_VAGAS):
        self.vida, self._dados, self._trava = vida, {}, threading.Lock()

    def buscar(self, termo: str, cfg: dict) -> list:
        chave = normalizar(termo).strip()
        with self._trava:
            item = self._dados.get(chave)
            if item and time.time() - item[0] < self.vida:
                return item[1]
        vagas = fontes.buscar_gupy(cfg, [termo])
        with self._trava:
            self._dados[chave] = (time.time(), vagas)
        return vagas


# ---------- leitura do currículo ----------
class ErroEnvio(ValueError):
    pass


def ler_pdf(dados: bytes) -> str:
    if not dados.startswith(b"%PDF"):
        raise ErroEnvio("O arquivo precisa ser um PDF.")
    from pypdf import PdfReader
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    try:
        leitor = PdfReader(io.BytesIO(dados))
        texto = "\n".join((p.extract_text() or "") for p in leitor.pages[:6])
    except Exception as e:  # noqa: BLE001
        raise ErroEnvio(f"Não consegui abrir esse PDF ({type(e).__name__}). Tente exportá-lo de novo.") from e
    if len(texto.strip()) < 200:
        raise ErroEnvio("Não encontrei texto nesse PDF. Se ele é uma foto ou um escaneado, exporte de novo "
                        "pelo Word, Google Docs ou Canva e envie outra vez.")
    return texto


# Usado quando a IA não está disponível e a pessoa não disse os cargos.
CARGOS_COMUNS = [
    "analista de suporte", "suporte técnico", "técnico de suporte", "técnico de ti", "analista de ti", "help desk", "service desk", "analista de redes",
    "analista de infraestrutura", "desenvolvedor", "programador", "analista de sistemas", "analista de dados",
    "analista de qualidade", "designer", "auxiliar administrativo", "assistente administrativo",
    "analista administrativo", "assistente financeiro", "analista financeiro", "auxiliar de contabilidade",
    "analista contábil", "faturista", "recepcionista", "atendente", "operador de telemarketing",
    "operador de caixa", "vendedor", "consultor de vendas", "representante comercial", "assistente comercial",
    "auxiliar de logística", "assistente de logística", "estoquista", "conferente", "almoxarife",
    "motorista", "técnico de enfermagem", "enfermeiro", "auxiliar de enfermagem", "farmacêutico",
    "assistente de rh", "analista de rh", "auxiliar de departamento pessoal", "analista de marketing",
    "social media", "eletricista", "técnico de manutenção", "mecânico", "auxiliar de produção",
    "operador de máquinas", "professor", "auxiliar de cozinha", "cozinheiro", "garçom",
]


def cargos_pelo_texto(texto: str, maximo: int = 3) -> list[str]:
    """Sem IA: cargos conhecidos citados no currículo. O começo (objetivo, resumo, emprego atual)
    vale o triplo, e cargos citados bem menos que o principal ficam de fora (ex.: um emprego antigo)."""
    t = normalizar(texto)
    inicio = t[: max(600, len(t) // 4)]
    pontos = sorted(((t.count(normalizar(c)) + 2 * inicio.count(normalizar(c)), c) for c in CARGOS_COMUNS), reverse=True)
    if not pontos or pontos[0][0] == 0:
        return []
    corte = pontos[0][0] / 2
    return [c for n, c in pontos if n > 0 and n >= corte][:maximo]


def _lista(valor: str) -> list[str]:
    return [p.strip() for p in (valor or "").replace(";", ",").replace("\n", ",").split(",") if p.strip()][:5]


# ---------- o processamento ----------
def processar(job: dict, texto: str, cargos: list[str], cidade: str, remoto: bool, cfg: dict,
              usar_ia: bool, cache: CacheVagas, modelo: str, vagas_com_ia: int):
    """Roda em segundo plano. Atualiza `job` conforme avança. Nunca guarda `texto` no job."""
    try:
        job["etapa"] = "perfil"
        resumo = ""
        if not cargos and usar_ia:
            try:
                perfil = sugerir_perfil(texto)
                cargos, resumo = perfil["cargos"][:5], perfil["resumo"]
            except Exception as e:  # noqa: BLE001
                log.warning("Perfil com IA falhou: %s", type(e).__name__)
        if not cargos:
            cargos = cargos_pelo_texto(texto)
        if not cargos:
            raise ErroEnvio("Não consegui descobrir pelo currículo quais cargos buscar. "
                            "Escreva os cargos que você procura e envie de novo.")
        job["perfil"] = {"cargos": cargos, "resumo": resumo}

        job["etapa"] = "busca"
        brutas = []
        for c in cargos:
            brutas.extend(cache.buscar(c, cfg))
        busca = {"cidades": [cidade] if cidade else [], "aceitar_remoto": remoto or not cidade,
                 "dias_maximos": 30, "palavras_excluidas": []}
        vagas = fontes.filtrar(brutas, busca)
        job["encontradas"] = len(vagas)
        if not vagas:
            job.update(etapa="pronto", vagas=[])
            return

        job["etapa"] = "analise"
        notas = sorted(((nota_rapida(texto, v), v) for v in vagas), key=lambda x: x[0], reverse=True)
        candidatas = notas[: max(vagas_com_ia, 10)]
        resultado = []

        if usar_ia:
            escolhidas = candidatas[:vagas_com_ia]
            job["progresso"] = [0, len(escolhidas)]
            candidato = {"resumo": resumo}

            def analisar(par):
                nota_palavras, v = par
                try:
                    return v, analisar_com_ia(texto, v, candidato, modelo)
                except Exception as e:  # noqa: BLE001
                    log.warning("Análise de uma vaga falhou: %s", type(e).__name__)
                    return v, None
                finally:
                    job["progresso"][0] += 1

            with ThreadPoolExecutor(max_workers=4) as ex:
                for v, a in ex.map(analisar, escolhidas):
                    if a:
                        resultado.append(_vaga_json(v, a.nota, a.resumo, a.pontos_fortes, a.lacunas, "ia"))
            job["usou_ia"] = bool(resultado)
        if not resultado:
            resultado = [_vaga_json(v, n, f"{n}% de compatibilidade por palavras-chave.", [], [], "palavras")
                         for n, v in candidatas]
        resultado.sort(key=lambda x: x["nota"], reverse=True)
        boas = [v for v in resultado if v["nota"] >= NOTA_MINIMA_MOSTRAR]
        job.update(etapa="pronto", vagas=boas[:10], abaixo=len(resultado) - len(boas[:10]))
    except ErroEnvio as e:
        job.update(etapa="erro", erro=str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("Falha ao processar um currículo")
        job.update(etapa="erro", erro=f"Algo deu errado do nosso lado ({type(e).__name__}). Tente de novo em instantes.")
    finally:
        texto = None    # noqa: F841 - o currículo sai da memória junto com esta função


def _vaga_json(v, nota, resumo, fortes, lacunas, metodo) -> dict:
    return {"titulo": v.titulo, "empresa": v.empresa, "cidade": v.cidade, "remoto": v.remoto, "url": v.url,
            "nota": int(nota), "resumo": resumo, "pontos_fortes": list(fortes)[:4], "lacunas": list(lacunas)[:4],
            "metodo": metodo, "publicada_em": v.publicada_em.date().isoformat() if v.publicada_em else None}


# ---------- o site ----------
def criar_app(limites: Limites | None = None, cache: CacheVagas | None = None, rodar_em_segundo_plano: bool = True) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_PDF + 64 * 1024
    limites = limites or Limites(_env_int("ANALISES_POR_PESSOA_DIA", 3), _env_int("ANALISES_IA_DIA", 50))
    cache = cache or CacheVagas()
    modelo = os.getenv("MODELO_SITE") or ia.MODELO_RAPIDO
    vagas_com_ia = _env_int("VAGAS_COM_IA", 12)
    cfg = completar({"busca": {"fontes": {"gupy": True}}})
    trabalhos: dict[str, dict] = {}
    trava = threading.Lock()

    def limpar_antigos():
        agora = time.time()
        with trava:
            for k in [k for k, j in trabalhos.items() if agora - j["criado"] > VIDA_RESULTADO]:
                del trabalhos[k]

    def ip_da_pessoa() -> str:
        if os.getenv("RENDER") or os.getenv("CONFIAR_PROXY"):
            return (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()
        return request.remote_addr or ""

    def erro(msg, codigo=400):
        return jsonify({"erro": msg}), codigo

    @app.errorhandler(413)
    def grande_demais(_):
        return erro("O arquivo é grande demais. Envie um PDF de até 5 MB.", 413)

    @app.get("/")
    def inicio():
        return send_file(PASTA / "web.html")

    @app.get("/privacidade")
    def privacidade():
        html = (PASTA / "web_privacidade.html").read_text(encoding="utf-8")
        contato = os.getenv("CONTATO_EMAIL", "").strip()
        html = html.replace("{{CONTATO}}", f'pelo e-mail <a href="mailto:{contato}">{contato}</a>' if contato
                            else "pela página do projeto no GitHub")
        return Response(html, mimetype="text/html")

    @app.get("/saude")
    def saude():
        return "ok"

    @app.get("/api/info")
    def info():
        return jsonify({"ia": ia.disponivel(), "limite_por_pessoa": limites.por_pessoa})

    @app.post("/api/analisar")
    def analisar():
        limpar_antigos()
        if request.form.get("aceite") != "1":
            return erro("Para continuar, confirme que leu como seus dados são usados.")
        arquivo = request.files.get("curriculo")
        if not arquivo or not arquivo.filename:
            return erro("Escolha o PDF do seu currículo.")
        try:
            texto = ler_pdf(arquivo.read())
        except ErroEnvio as e:
            return erro(str(e))
        cargos = _lista(request.form.get("cargos", ""))
        cidade = (request.form.get("cidade") or "").strip()[:60]
        remoto = request.form.get("remoto") == "1"
        if not limites.registrar_pessoa(ip_da_pessoa()):
            return erro(f"Você já fez {limites.por_pessoa} análises hoje. Volte amanhã para fazer mais.", 429)
        usar_ia = ia.disponivel() and limites.reservar_ia()
        if not usar_ia and not cargos and not cargos_pelo_texto(texto):
            return erro("Escreva os cargos que você procura: hoje não consigo descobri-los pelo currículo.")

        id_ = uuid.uuid4().hex
        job = {"criado": time.time(), "etapa": "inicio", "progresso": [0, 0], "perfil": None, "vagas": None,
               "encontradas": 0, "abaixo": 0, "usou_ia": False, "ia_esgotada": ia.disponivel() and not usar_ia, "erro": None,
               "cidade": cidade}
        with trava:
            trabalhos[id_] = job
        args = (job, texto, cargos, cidade, remoto, cfg, usar_ia, cache, modelo, vagas_com_ia)
        if rodar_em_segundo_plano:
            threading.Thread(target=processar, args=args, daemon=True).start()
        else:
            processar(*args)
        del texto
        return jsonify({"id": id_})

    @app.get("/api/analisar/<id_>")
    def andamento(id_):
        job = trabalhos.get(id_)
        if not job:
            return erro("Esse resultado expirou ou não existe. Envie o currículo de novo.", 404)
        publico = {k: v for k, v in job.items() if k != "criado"}
        publico["expira_em_min"] = max(0, int((VIDA_RESULTADO - (time.time() - job["criado"])) // 60))
        return jsonify(publico)

    return app


def rodar(porta: int = 8000):
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    print(f"Site rodando em http://127.0.0.1:{porta}  (Ctrl+C para parar)")
    criar_app().run(host="127.0.0.1", port=porta, debug=False, threaded=True)
