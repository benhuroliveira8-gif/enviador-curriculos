"""Envio por SMTP: candidaturas (com o currículo anexo) e avisos para você mesmo."""
import mimetypes
import smtplib
from email.message import EmailMessage
from pathlib import Path


def _conectar(smtp: dict) -> smtplib.SMTP:
    con = smtplib.SMTP(smtp["servidor"], smtp.get("porta", 587), timeout=30)
    con.starttls()
    con.login(smtp["usuario"], smtp["senha"])
    return con


def _remetente(smtp: dict, nome: str) -> str:
    # O "De" precisa ser a conta que autentica no SMTP, senão Gmail/Outlook rejeitam ou marcam como spam.
    return f"{nome} <{smtp['usuario']}>"


class Remetente:
    def __init__(self, smtp: dict, candidato: dict, copia_para_mim: bool = True):
        self.smtp = smtp
        self.candidato = candidato
        self.copia = copia_para_mim
        self._con = None

    def __enter__(self):
        self._con = _conectar(self.smtp)
        return self

    def __exit__(self, *exc):
        if self._con:
            self._con.quit()

    def enviar(self, para: str, assunto: str, corpo: str):
        msg = montar_email(self.candidato, para, assunto, corpo, self.smtp)
        destinatarios = [para] + ([self.candidato["email"]] if self.copia else [])
        self._con.send_message(msg, to_addrs=destinatarios)


def montar_email(candidato: dict, para: str, assunto: str, corpo: str, smtp: dict | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = _remetente(smtp, candidato["nome"]) if smtp else f'{candidato["nome"]} <{candidato["email"]}>'
    msg["To"] = para
    msg["Reply-To"] = candidato["email"]
    msg["Subject"] = assunto
    msg.set_content(corpo)
    pdf = Path(candidato["curriculo_pdf"])
    tipo = (mimetypes.guess_type(pdf.name)[0] or "application/pdf").split("/")
    msg.add_attachment(pdf.read_bytes(), maintype=tipo[0], subtype=tipo[1],
                       filename=f'Curriculo - {candidato["nome"]}{pdf.suffix}')
    return msg


def enviar_aviso(smtp: dict, para: str, assunto: str, html: str, texto: str):
    """E-mail para você mesmo (resumo diário). Versão em texto + HTML."""
    msg = EmailMessage()
    msg["From"] = _remetente(smtp, "Enviador de Currículos")
    msg["To"] = para
    msg["Subject"] = assunto
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")
    con = _conectar(smtp)
    try:
        con.send_message(msg)
    finally:
        con.quit()
