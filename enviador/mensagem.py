"""Monta o assunto e o corpo do e-mail de candidatura."""
import logging
import os

log = logging.getLogger(__name__)
MODELO_IA = "claude-haiku-5-5"


def limpar_cargo(titulo: str, empresa: str = "") -> str:
    """'[Remoto] Analista NOC na Empresa X' -> 'Analista NOC'"""
    import re
    cargo = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", titulo).strip(" -|")
    if empresa:
        cargo = re.sub(rf"\s+(?:na|no|@|para|-|\|)\s+{re.escape(empresa)}\s*$", "", cargo, flags=re.I)
    return cargo.strip(" -|") or "a vaga"


def _campos(vaga, candidato: dict) -> dict:
    return {
        "nome": candidato.get("nome", ""),
        "telefone": candidato.get("telefone", ""),
        "linkedin": candidato.get("linkedin", ""),
        "resumo": (candidato.get("resumo") or "").strip(),
        "cargo": limpar_cargo(vaga.titulo, vaga.empresa),
        "empresa": vaga.empresa,
        "empresa_frase": f" da empresa {vaga.empresa}" if vaga.empresa else "",
    }


def montar_assunto(vaga, config: dict) -> str:
    return config["mensagem"]["assunto"].format(**_campos(vaga, config["candidato"]))


def montar_corpo(vaga, config: dict, analise=None) -> str:
    candidato = config["candidato"]
    if config["mensagem"].get("usar_ia") and os.getenv("ANTHROPIC_API_KEY"):
        try:
            return _corpo_com_ia(vaga, candidato, analise)
        except Exception as e:
            log.warning("IA indisponível, usando modelo fixo: %s", e)
    return config["mensagem"]["modelo"].format(**_campos(vaga, candidato))


def _corpo_com_ia(vaga, candidato: dict, analise=None) -> str:
    import anthropic
    cliente = anthropic.Anthropic()
    destaques = ""
    if analise and analise.pontos_fortes:
        destaques = "Destaque estes pontos fortes: " + "; ".join(analise.pontos_fortes) + "\n"
    prompt = destaques + (
        "Escreva um e-mail curto (máx. 120 palavras) em português do Brasil, tom profissional e "
        "natural, para acompanhar um currículo em anexo. Não invente experiências: use apenas o "
        "resumo do candidato. Termine com nome, telefone e LinkedIn. Responda só com o corpo do e-mail.\n\n"
        f"Candidato: {candidato.get('nome')}\nResumo: {candidato.get('resumo')}\n"
        f"Telefone: {candidato.get('telefone')}\nLinkedIn: {candidato.get('linkedin')}\n\n"
        f"Vaga: {vaga.titulo}\nEmpresa: {vaga.empresa or 'não informada'}\n"
        f"Descrição:\n{vaga.descricao[:3000]}"
    )
    resp = cliente.messages.create(model=MODELO_IA, max_tokens=500,
                                   messages=[{"role": "user", "content": prompt}])
    return resp.content[0].text.strip()
