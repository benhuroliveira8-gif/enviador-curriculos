"""Acesso à IA (Claude, da Anthropic) num lugar só.

A chave pode vir da variável de ambiente ANTHROPIC_API_KEY ou do config.yaml (ia.chave_api).
"""
import json
import logging
import os
import re

log = logging.getLogger(__name__)

MODELO_FORTE = "claude-sonnet-5-5"     # análises que exigem cuidado
MODELO_RAPIDO = "claude-haiku-5-5"     # textos curtos


class ErroIA(Exception):
    pass


def disponivel() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def aplicar_chave(config: dict):
    """Se o config tem uma chave e o ambiente não, usa a do config."""
    chave = ((config or {}).get("ia") or {}).get("chave_api") or ""
    if chave.strip() and not os.getenv("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = chave.strip()


def extrair_json(texto: str):
    m = re.search(r"\{.*\}|\[.*\]", texto or "", re.DOTALL)
    try:
        return json.loads(m.group(0) if m else texto)
    except (json.JSONDecodeError, TypeError) as e:
        raise ErroIA(f"A IA respondeu num formato inesperado: {e}") from e


def perguntar(prompt: str, modelo: str = MODELO_FORTE, max_tokens: int = 1500, chave: str | None = None) -> str:
    if not (chave or disponivel()):
        raise ErroIA("Chave da Anthropic não configurada.")
    import anthropic
    cliente = anthropic.Anthropic(api_key=chave) if chave else anthropic.Anthropic()
    resp = cliente.messages.create(model=modelo, max_tokens=max_tokens,
                                   messages=[{"role": "user", "content": prompt}])
    return "".join(getattr(b, "text", "") for b in resp.content).strip()


def pedir_json(prompt: str, modelo: str = MODELO_FORTE, max_tokens: int = 1500):
    return extrair_json(perguntar(prompt, modelo, max_tokens))


def testar_chave(chave: str) -> tuple[bool, str]:
    """Faz uma chamada mínima para ver se a chave funciona."""
    chave = (chave or "").strip()
    if not chave:
        return False, "Informe a chave."
    if not chave.startswith("sk-"):
        return False, "A chave da Anthropic começa com 'sk-'. Confira se copiou inteira."
    try:
        perguntar("Responda apenas: ok", MODELO_RAPIDO, 5, chave=chave)
        return True, "Chave funcionando."
    except Exception as e:  # noqa: BLE001 - a mensagem vai para a pessoa
        msg = str(e)
        if "401" in msg or "authentication" in msg.lower():
            return False, "A Anthropic recusou a chave. Gere uma nova em console.anthropic.com."
        if "credit" in msg.lower() or "billing" in msg.lower():
            return False, "A chave existe, mas a conta está sem crédito. Adicione crédito em console.anthropic.com."
        return False, f"Não consegui falar com a Anthropic: {msg[:200]}"
