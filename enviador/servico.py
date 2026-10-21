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
    p = Path(caminho)
    if not p.exists():
        raise ErroConfig(f"Arquivo {caminho} não encontrado. Copie config.example.yaml para config.yaml e preencha.")
    return yaml.safe_load(p.read_text(encoding="utf-8"))


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
