"""Extrai e-mails de contato do texto de uma vaga."""
import re

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Endereços que não são de recrutamento
_IGNORAR_PREFIXOS = ("noreply", "no-reply", "naoresponda", "nao-responda", "donotreply",
                     "notifications", "privacy", "privacidade", "dpo", "lgpd", "suporte", "support")
_IGNORAR_DOMINIOS = ("example.com", "exemplo.com", "email.com", "users.noreply.github.com",
                     "sentry.io", "github.com")
_IGNORAR_EXTENSOES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")


def extrair_emails(texto: str) -> list[str]:
    encontrados = []
    for bruto in _EMAIL_RE.findall(texto or ""):
        email = bruto.strip(".").lower()
        local, _, dominio = email.partition("@")
        if email.endswith(_IGNORAR_EXTENSOES):
            continue
        if local.startswith(_IGNORAR_PREFIXOS) or dominio in _IGNORAR_DOMINIOS:
            continue
        if email not in encontrados:
            encontrados.append(email)
    return encontrados
