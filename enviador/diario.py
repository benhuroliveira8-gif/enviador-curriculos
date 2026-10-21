"""Rotina diária: busca vagas, analisa e avisa você por e-mail quando houver algo importante.

Pensada para rodar sozinha pelo Agendador de Tarefas do Windows (veja agendar_tarefa.ps1).
Cada execução grava um resumo em relatorios/ e um registro em logs/diario.log.
"""
from dataclasses import dataclass, field
from datetime import date, datetime
import html
import logging
from pathlib import Path

from . import raiox
from .banco import ETAPAS
from .servico import carregar_cv, enviar_por_email, rodar_busca

log = logging.getLogger(__name__)


@dataclass
class Resumo:
    data: str
    encontradas: int = 0
    novas: int = 0
    destaques: list = field(default_factory=list)      # [(Vaga, Analise)] com nota >= nota_alerta
    outras_recomendadas: int = 0
    fila_total: int = 0
    followups: list = field(default_factory=list)      # linhas do banco
    emails_enviados: int = 0
    faltam: list = field(default_factory=list)         # ItemRaiox
    erro: str = ""

    @property
    def tem_novidade(self) -> bool:
        return bool(self.destaques or self.followups or self.emails_enviados or self.erro)


def montar(config: dict, banco, cv: str | None = None) -> Resumo:
    aviso = config.get("aviso", {})
    nota_alerta = aviso.get("nota_alerta", 75)
    dias_followup = config.get("acompanhamento", {}).get("dias_followup", 10)
    r = Resumo(data=date.today().strftime("%d/%m/%Y"))
    try:
        cv = cv if cv is not None else carregar_cv(config)
        res = rodar_busca(config, banco, cv)
        r.encontradas, r.novas = res.encontradas, res.novas
        r.destaques = [(v, a) for v, a in res.recomendadas if a.nota >= nota_alerta]
        r.outras_recomendadas = len(res.recomendadas) - len(r.destaques)
        if config.get("envio", {}).get("automatico_no_diario") and not config["envio"].get("modo_teste", True):
            r.emails_enviados = enviar_por_email(config, banco, res.recomendadas, saida=log.info)
        r.faltam = raiox.calcular(banco.vagas_analisadas(), cv, config).faltam[:3]
    except Exception as e:                     # o aviso de erro também é útil: você fica sabendo
        log.exception("Falha na rotina diária")
        r.erro = f"{type(e).__name__}: {e}"
    r.fila_total = len(banco.fila_candidaturas())
    r.followups = banco.followups(dias_followup)
    return r


# ---------- formatação ----------
def plural(n: int, um: str, varios: str) -> str:
    return f"{n} {um if n == 1 else varios}"


def _e(t) -> str:
    return html.escape(str(t or ""))


def _dias(desde_iso: str) -> int:
    try:
        return (datetime.now() - datetime.fromisoformat(desde_iso)).days
    except (TypeError, ValueError):
        return 0


def _ha(desde_iso: str) -> str:
    d = _dias(desde_iso)
    return "hoje" if d == 0 else "há 1 dia" if d == 1 else f"há {d} dias"


def assunto(r: Resumo) -> str:
    partes = []
    if r.destaques:
        partes.append(plural(len(r.destaques), "vaga com nota alta", "vagas com nota alta"))
    if r.followups:
        partes.append(plural(len(r.followups), "follow-up", "follow-ups"))
    if r.erro:
        partes.append("erro na busca")
    return "Vagas do dia — " + (", ".join(partes) if partes else "sem novidades") + f" ({r.data})"


def texto(r: Resumo) -> str:
    linhas = [assunto(r), "", f"Busca: {r.encontradas} vagas encontradas, {r.novas} novas."]
    if r.erro:
        linhas += ["", f"ATENÇÃO: a busca falhou ({r.erro}). Veja logs/diario.log."]
    if r.destaques:
        linhas += ["", "VAGAS COM NOTA ALTA"]
        for v, a in r.destaques:
            linhas += [f"[{a.nota}] {v.titulo} | {v.empresa or '?'}", f"    {a.resumo}", f"    {v.url}"]
    if r.followups:
        linhas += ["", "HORA DE FAZER FOLLOW-UP"]
        for f in r.followups:
            linhas.append(f"- {f['titulo']} | {f['empresa'] or '?'} — {ETAPAS.get(f['etapa'], f['etapa'])} "
                          f"{_ha(f['etapa_em'])}")
    linhas += ["", f"Na fila para candidatura: {plural(r.fila_total, 'vaga', 'vagas')}. "
                   "Abra o painel (python -m enviador painel) ou rode python -m enviador candidatar."]
    return "\n".join(linhas) + "\n"


_COR = {"alta": "#1E7A52", "media": "#2350C8"}


def html_resumo(r: Resumo) -> str:
    def cartao_vaga(v, a):
        cor = _COR["alta"] if a.nota >= 85 else _COR["media"]
        fortes = ", ".join(a.pontos_fortes[:4])
        falta = ", ".join(a.lacunas[:3])
        return f"""
        <tr><td style="padding:14px 16px;border:1px solid #D5DBE2;border-radius:10px;background:#fff">
          <div style="font:600 22px/1 Arial;color:{cor}">{a.nota}<span style="font:13px Arial;color:#5D6B7A"> de compatibilidade</span></div>
          <div style="font:600 16px/1.35 Arial;color:#16212E;margin:6px 0 2px">{_e(v.titulo)}</div>
          <div style="font:14px/1.4 Arial;color:#5D6B7A">{_e(', '.join(x for x in (v.empresa, v.cidade, 'remoto' if v.remoto else '') if x))}</div>
          <div style="font:14px/1.5 Arial;color:#16212E;margin-top:8px">{_e(a.resumo)}</div>
          {f'<div style="font:13px/1.5 Arial;color:#1E7A52;margin-top:6px">A favor: {_e(fortes)}</div>' if fortes else ''}
          {f'<div style="font:13px/1.5 Arial;color:#A85A12">Falta: {_e(falta)}</div>' if falta else ''}
          <a href="{_e(v.url)}" style="display:inline-block;margin-top:10px;padding:8px 14px;background:#2350C8;color:#fff;border-radius:6px;font:600 13px Arial;text-decoration:none">Ver vaga</a>
        </td></tr><tr><td style="height:10px"></td></tr>"""

    blocos = []
    if r.erro:
        blocos.append(f'<p style="padding:12px 14px;background:#fdecea;color:#8c1d18;border-radius:8px;font:14px/1.5 Arial">'
                      f'A busca de hoje falhou: {_e(r.erro)}. Veja <code>logs/diario.log</code>.</p>')
    if r.destaques:
        blocos.append('<h2 style="font:600 15px Arial;color:#16212E;margin:22px 0 10px">Vagas com nota alta</h2>'
                      '<table width="100%" cellspacing="0" cellpadding="0">'
                      + "".join(cartao_vaga(v, a) for v, a in r.destaques) + "</table>")
    if r.followups:
        itens = "".join(
            f'<li style="margin:4px 0">{_e(f["titulo"])} — {_e(f["empresa"] or "?")} '
            f'<span style="color:#5D6B7A">({_e(ETAPAS.get(f["etapa"], f["etapa"]))} {_ha(f["etapa_em"])})</span></li>'
            for f in r.followups)
        blocos.append('<h2 style="font:600 15px Arial;color:#16212E;margin:22px 0 6px">Hora de fazer follow-up</h2>'
                      '<p style="font:14px/1.5 Arial;color:#5D6B7A;margin:0 0 6px">Sem novidade há algum tempo. '
                      'Um e-mail curto ao recrutador mostra interesse.</p>'
                      f'<ul style="font:14px/1.5 Arial;color:#16212E;padding-left:18px">{itens}</ul>')
    if r.faltam:
        itens = "".join(f"<li>{_e(i.habilidade)}: pedido em {i.percentual}% das vagas da sua área</li>" for i in r.faltam)
        blocos.append('<h2 style="font:600 15px Arial;color:#16212E;margin:22px 0 6px">O que mais aparece e falta no seu currículo</h2>'
                      f'<ul style="font:14px/1.5 Arial;color:#16212E;padding-left:18px">{itens}</ul>')

    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>{_e(assunto(r))}</title></head>
<body style="margin:0;background:#EEF1F4;padding:24px 12px">
<table width="100%" cellspacing="0" cellpadding="0"><tr><td align="center">
<table width="600" style="max-width:600px;width:100%" cellspacing="0" cellpadding="0"><tr><td>
  <div style="font:14px Arial;color:#5D6B7A">Vagas do dia, {_e(r.data)}</div>
  <h1 style="font:600 22px/1.3 Arial;color:#16212E;margin:6px 0 4px">
    {_e(plural(len(r.destaques), 'vaga com nota alta', 'vagas com nota alta'))}{_e(', ' + plural(len(r.followups), 'follow-up', 'follow-ups')) if r.followups else ''}</h1>
  <p style="font:14px/1.5 Arial;color:#5D6B7A;margin:0">{plural(r.encontradas, 'vaga encontrada', 'vagas encontradas')}, {plural(r.novas, 'nova', 'novas')}.
    {plural(r.fila_total, 'vaga espera', 'vagas esperam')} sua decisão no painel.</p>
  {''.join(blocos)}
  <p style="font:13px/1.5 Arial;color:#5D6B7A;margin-top:24px">Para decidir e se candidatar, abra o painel:
    <code>python -m enviador painel</code></p>
</td></tr></table></td></tr></table></body></html>"""


def salvar(r: Resumo, pasta: Path = Path("relatorios")) -> Path:
    pasta.mkdir(exist_ok=True)
    caminho = pasta / f"diario-{date.today().isoformat()}.html"
    caminho.write_text(html_resumo(r), encoding="utf-8")
    return caminho


def executar(config: dict, banco, saida=print, cv: str | None = None) -> Resumo:
    r = montar(config, banco, cv)
    caminho = salvar(r)
    saida(texto(r))
    saida(f"Resumo salvo em {caminho}")

    aviso = config.get("aviso", {})
    smtp = config.get("smtp", {})
    if not aviso.get("email", True):
        return r
    if not (smtp.get("senha") and smtp.get("usuario")):
        saida("E-mail de aviso não enviado: preencha usuario e senha em smtp no config.yaml.")
        return r
    if not r.tem_novidade and not aviso.get("enviar_sem_novidades", False):
        saida("Sem novidades hoje: nenhum e-mail enviado.")
        return r
    from .remetente import enviar_aviso
    para = aviso.get("para") or config["candidato"]["email"]
    try:
        enviar_aviso(smtp, para, assunto(r), html_resumo(r), texto(r))
        saida(f"Aviso enviado para {para}.")
    except Exception as e:
        log.exception("Falha ao enviar o aviso")
        saida(f"Não consegui enviar o aviso por e-mail: {e}")
    return r


def configurar_log(pasta: Path = Path("logs")):
    pasta.mkdir(exist_ok=True)
    h = logging.FileHandler(pasta / "diario.log", encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(h)
    logging.getLogger().setLevel(logging.INFO)
