"""Operações principais, compartilhadas pelo terminal, pela rotina diária e pelo painel."""
from dataclasses import dataclass, field
import logging
import random
import time
from pathlib import Path

import yaml

from .analise import analisar_vagas, ler_curriculo
from .fontes import buscar_todas
from .mensagem import montar_assunto, montar_corpo

log = logging.getLogger(__name__)


class ErroConfig(Exception):
    pass


def carregar_config(caminho: str = "config.yaml") -> dict:
    from .configuracao import completar
    from .ia import aplicar_chave
    p = Path(caminho)
    if not p.exists():
        raise ErroConfig(f"Arquivo {caminho} não encontrado. Rode `python -m enviador configurar` para criar.")
    try:
        cfg = completar(yaml.safe_load(p.read_text(encoding="utf-8")))
    except yaml.YAMLError as e:
        raise ErroConfig(f"O arquivo {caminho} tem um erro de formatação: {e}. "
                         f"Se você editou à mão, compare com config.example.yaml (ou restaure {caminho}.bak).")
    aplicar_chave(cfg)
    return cfg


def carregar_cv(config: dict) -> str:
    cv_path = config["candidato"]["curriculo_pdf"]
    if not Path(cv_path).exists():
        raise ErroConfig(f"Currículo não encontrado: {cv_path}. A análise precisa dele.")
    cv = ler_curriculo(cv_path)
    if len(cv.strip()) < 200:
        log.warning("Pouco texto extraído do PDF. Se o currículo for uma imagem escaneada, a análise fica fraca.")
    return cv


def texto_analise(a) -> str:
    partes = [a.resumo]
    if a.pontos_fortes:
        partes.append("A favor: " + "; ".join(a.pontos_fortes))
    if a.lacunas:
        partes.append("Lacunas: " + "; ".join(a.lacunas))
    return " | ".join(p for p in partes if p)


@dataclass
class ResultadoBusca:
    encontradas: int = 0
    novas: int = 0
    analisadas: list = field(default_factory=list)       # [(Vaga, Analise)], melhor nota primeiro

    @property
    def recomendadas(self):
        return [(v, a) for v, a in self.analisadas if a.recomendada]


def rodar_busca(config: dict, banco, cv: str | None = None) -> ResultadoBusca:
    """Busca em todas as fontes, guarda as vagas novas, analisa e salva as notas."""
    cv = cv if cv is not None else carregar_cv(config)
    vagas = buscar_todas(config)
    novas = [v for v in vagas if banco.registrar_vaga(v)]
    res = ResultadoBusca(encontradas=len(vagas), novas=len(novas))
    if novas:
        res.analisadas = analisar_vagas(novas, cv, config)
        for v, a in res.analisadas:
            banco.salvar_analise(v.chave, a.nota, texto_analise(a), a.recomendada,
                                 a.lacunas, a.pontos_fortes, a.metodo)
    return res


def bloqueada(vaga, email: str, bloqueios: list[str]) -> bool:
    alvo = f"{vaga.empresa} {email}".lower()
    return any(b.lower() in alvo for b in bloqueios)


def enviar_por_email(config: dict, banco, recomendadas, saida=print) -> int:
    """Candidata-se por e-mail às recomendadas que trazem endereço. Respeita modo_teste e limites.
    Retorna quantos e-mails foram (ou, em modo teste, seriam) enviados."""
    envio = config["envio"]
    teste = envio.get("modo_teste", True)
    if teste:
        saida(">>> MODO TESTE: nada será enviado. Mude modo_teste para false quando estiver satisfeito.\n")

    fila = []
    for v, a in recomendadas:          # já ordenadas: melhores vagas primeiro
        if not v.aceita_email:
            continue
        email = v.emails[0]
        if banco.ja_enviado_para(email) or bloqueada(v, email, envio.get("empresas_bloqueadas", [])):
            continue
        fila.append((v, a, email))
    if not teste:
        fila = fila[:max(envio.get("max_por_dia", 15) - banco.enviados_hoje(), 0)]
    if not fila:
        saida("Nenhuma candidatura por e-mail para fazer agora.")
        return 0

    remetente = None
    if not teste:
        from .remetente import Remetente
        remetente = Remetente(config["smtp"], config["candidato"], envio.get("copia_para_mim", True)).__enter__()
    feitos = 0
    try:
        for n, (v, a, email) in enumerate(fila, 1):
            assunto, corpo = montar_assunto(v, config), montar_corpo(v, config, a)
            saida(f"[{n}/{len(fila)}] Nota {a.nota} | Para: {email}\nAssunto: {assunto}\n"
                  f"{'-' * 60}\n{corpo}\n{'=' * 60}\n")
            if teste:
                feitos += 1
                continue
            try:
                remetente.enviar(email, assunto, corpo)
                banco.registrar_envio(v.chave, email, True)
                feitos += 1
                saida("    ✓ enviado")
            except Exception as e:
                banco.registrar_envio(v.chave, email, False, str(e))
                saida(f"    ✗ falhou: {e}")
            if n < len(fila):
                time.sleep(random.uniform(*envio.get("intervalo_segundos", [60, 180])))
    finally:
        if remetente:
            remetente.__exit__(None, None, None)
    return feitos


# ---------- vaga adicionada à mão (InfoJobs, LinkedIn, Catho, indicação...) ----------
class ErroVaga(ValueError):
    pass


def _fonte_do_link(url: str) -> str:
    import re
    m = re.search(r"https?://(?:www\.|[a-z0-9-]+\.)?([a-z0-9-]+)\.(?:com|io|net|org)", (url or "").lower())
    return m.group(1) if m else "manual"


def adicionar_vaga(config: dict, banco, titulo: str, descricao: str, empresa: str = "", url: str = "",
                   cidade: str = "", remoto: bool = False, cv: str | None = None):
    """Cadastra uma vaga colada pela pessoa, analisa e coloca na fila (mesmo com nota baixa:
    foi você que escolheu). Retorna (linha_do_banco, nova: bool)."""
    import hashlib
    from .extrator import extrair_emails
    from .modelos import Vaga
    titulo, descricao = (titulo or "").strip(), (descricao or "").strip()
    if not titulo:
        raise ErroVaga("Informe o cargo da vaga.")
    if len(descricao) < 40:
        raise ErroVaga("Cole a descrição da vaga (requisitos e atividades). Sem ela não dá para analisar.")
    url = (url or "").strip()
    base = url or f"{titulo}|{empresa}".lower()
    v = Vaga(fonte=f"manual:{_fonte_do_link(url)}", id_externo=hashlib.sha1(base.encode()).hexdigest()[:12],
             titulo=titulo, empresa=(empresa or "").strip(), descricao=descricao, url=url,
             cidade=(cidade or "").strip(), remoto=bool(remoto), emails=extrair_emails(descricao))
    if not banco.registrar_vaga(v):
        return banco.vaga(v.chave), False
    cv = cv if cv is not None else carregar_cv(config)
    cfg = dict(config, analise=dict(config.get("analise", {}), nota_minima_pre_filtro=0))
    (_, a), = analisar_vagas([v], cv, cfg)
    banco.salvar_analise(v.chave, a.nota, texto_analise(a), a.recomendada, a.lacunas, a.pontos_fortes,
                         a.metodo, status="nova")
    return banco.vaga(v.chave), True


def reanalisar(config: dict, banco, cv: str | None = None, limite: int | None = None) -> dict:
    """Refaz a análise, agora com IA, das vagas que foram avaliadas só por palavras-chave.
    Começa pelas de maior nota. Vagas adiadas continuam adiadas."""
    from . import ia
    from .candidatura import vaga_do_banco
    if not ia.disponivel():
        raise ErroConfig("Configure a chave da Anthropic antes de reanalisar.")
    cv = cv if cv is not None else carregar_cv(config)
    limite = limite or config.get("analise", {}).get("max_analises_ia", 30)
    linhas = [r for r in banco.listar(("nova", "depois", "baixa")) if (r["metodo"] or "") != "ia"]
    linhas = sorted(linhas, key=lambda r: r["nota"] or 0, reverse=True)[:limite]
    if not linhas:
        return {"analisadas": 0, "recomendadas": 0, "mudaram": 0}
    cfg = dict(config, analise=dict(config.get("analise", {}), max_analises_ia=limite))
    antes = {r["chave"]: r["status"] for r in linhas}
    resultado = analisar_vagas([vaga_do_banco(r) for r in linhas], cv, cfg)
    mudaram = 0
    for v, a in resultado:
        banco.salvar_analise(v.chave, a.nota, texto_analise(a), a.recomendada, a.lacunas, a.pontos_fortes, a.metodo)
        depois = banco.vaga(v.chave)["status"]
        mudaram += (antes[v.chave] == "baixa") != (depois == "baixa")
    return {"analisadas": sum(1 for _, a in resultado if a.metodo == "ia"),
            "recomendadas": sum(1 for _, a in resultado if a.recomendada), "mudaram": mudaram}
