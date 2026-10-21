from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import yaml

from enviador.banco import Banco
from enviador.extrator import extrair_emails
from enviador.fontes import buscar_github, buscar_gupy, filtrar
from enviador.mensagem import montar_assunto, montar_corpo
from enviador.modelos import Vaga
from enviador.remetente import montar_email

CONFIG = yaml.safe_load(open("config.example.yaml", encoding="utf-8"))


class Resp:
    def __init__(self, dados): self.dados = dados
    def raise_for_status(self): pass
    def json(self): return self.dados


def test_extrai_emails_ignora_lixo():
    texto = ("Envie para Vagas@Empresa.com.br. Dúvidas: noreply@empresa.com, "
             "logo@2x.png, fulano@users.noreply.github.com, rh@empresa.com.br")
    assert extrair_emails(texto) == ["vagas@empresa.com.br", "rh@empresa.com.br"]


def test_github_filtra_por_palavra_e_extrai_email():
    issues = [
        {"number": 1, "title": "[Remoto] Desenvolvedor Python na Acme", "body": "Mande CV para jobs@acme.io",
         "html_url": "u1", "labels": [], "created_at": datetime.now(timezone.utc).isoformat()},
        {"number": 2, "title": "Dev Java", "body": "x", "html_url": "u2", "labels": [], "created_at": None},
        {"number": 3, "title": "PR", "pull_request": {}, "body": "python"},
    ]
    with patch("enviador.fontes.requests.get", return_value=Resp(issues)):
        cfg = {"busca": {"repositorios_github": ["backend-br/vagas"]}}
        vagas = buscar_github(cfg, ["python"])
    assert len(vagas) == 1
    assert vagas[0].emails == ["jobs@acme.io"] and vagas[0].remoto and vagas[0].empresa == "Acme"


def test_gupy_converte_resposta():
    dados = {"data": [{"id": 9, "name": "Analista de Dados", "careerPageName": "Loja X",
                       "description": "Venha!", "jobUrl": "https://lojax.gupy.io/jobs/9",
                       "city": "Porto Alegre", "isRemoteWork": False, "publishedDate": "2026-10-10T12:00:00.000Z"}]}
    with patch("enviador.fontes.requests.get", return_value=Resp(dados)):
        vagas = buscar_gupy({}, ["analista"])
    assert vagas[0].empresa == "Loja X" and not vagas[0].aceita_email


def test_filtro_exclusao_cidade_e_data():
    agora = datetime.now(timezone.utc)
    vs = [Vaga("f", "1", "Dev Sênior", publicada_em=agora),
          Vaga("f", "2", "Dev", cidade="São Paulo", publicada_em=agora),
          Vaga("f", "3", "Dev", cidade="Porto Alegre", publicada_em=agora - timedelta(days=40)),
          Vaga("f", "4", "Dev", cidade="Porto Alegre", publicada_em=agora),
          Vaga("f", "5", "Dev", remoto=True, publicada_em=agora),
          Vaga("f", "4", "Dev duplicada", cidade="Porto Alegre")]
    busca = {"palavras_excluidas": ["sênior"], "cidades": ["Porto Alegre"], "dias_maximos": 15}
    assert [v.id_externo for v in filtrar(vs, busca)] == ["4", "5"]


def test_mensagem_e_email_com_anexo(tmp_path):
    pdf = tmp_path / "cv.pdf"
    pdf.write_bytes(b"%PDF-1.4 teste")
    cfg = dict(CONFIG, candidato=dict(CONFIG["candidato"], curriculo_pdf=str(pdf)))
    v = Vaga("f", "1", "Analista de Dados", empresa="Acme")
    assunto, corpo = montar_assunto(v, cfg), montar_corpo(v, cfg)
    assert assunto == "Candidatura - Analista de Dados - Seu Nome Completo"
    assert "equipe de recrutamento da empresa Acme" in corpo
    msg = montar_email(cfg["candidato"], "rh@acme.com", assunto, corpo)
    anexos = list(msg.iter_attachments())
    assert anexos[0].get_filename() == "Curriculo - Seu Nome Completo.pdf"


def test_banco_evita_duplicados(tmp_path):
    b = Banco(str(tmp_path / "h.db"))
    v = Vaga("f", "1", "Dev", emails=["rh@x.com"])
    assert b.registrar_vaga(v) and not b.registrar_vaga(v)
    b.registrar_envio(v.chave, "rh@x.com", True)
    assert b.ja_enviado_para("rh@x.com") and b.enviados_hoje() == 1


# ---------- Análise de compatibilidade ----------
from enviador.analise import analisar_vagas, interpretar_resposta_ia, nota_rapida

CV = ("Desenvolvedor Python com 3 anos de experiência em Django, FastAPI, PostgreSQL, Docker e AWS. "
      "Graduado em Ciência da Computação. Inglês intermediário. Testes automatizados com pytest.")


def test_nota_rapida_diferencia_vagas():
    boa = Vaga("f", "1", "Desenvolvedor Python", descricao="Django, FastAPI, PostgreSQL, Docker, pytest")
    ruim = Vaga("f", "2", "Enfermeiro", descricao="COREN ativo, plantões, UTI, atendimento hospitalar")
    assert nota_rapida(CV, boa) >= 65 > 25 > nota_rapida(CV, ruim)


def test_interpreta_json_da_ia_mesmo_com_texto_extra():
    a = interpretar_resposta_ia('Segue:\n{"nota": 120, "resumo": "ok", "pontos_fortes": ["Python"], "lacunas": []}')
    assert a.nota == 100 and a.pontos_fortes == ["Python"] and a.metodo == "ia"


def test_analise_usa_ia_so_nas_promissoras_e_ordena(monkeypatch):
    from enviador import analise as mod
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    chamadas = []

    def falsa_ia(cv, vaga, cand):
        chamadas.append(vaga.titulo)
        return mod.Analise(nota=82, recomendada=False, resumo="perfil forte", metodo="ia")

    monkeypatch.setattr(mod, "analisar_com_ia", falsa_ia)
    vagas = [Vaga("f", "2", "Enfermeiro", descricao="COREN, UTI, plantões"),
             Vaga("f", "1", "Desenvolvedor Python", descricao="Django FastAPI Docker")]
    res = analisar_vagas(vagas, CV, {"analise": {"nota_minima": 65}})
    assert chamadas == ["Desenvolvedor Python"]            # enfermeiro não gasta IA
    assert res[0][0].titulo == "Desenvolvedor Python" and res[0][1].recomendada
    assert not res[1][1].recomendada


def test_limpa_cargo():
    from enviador.mensagem import limpar_cargo
    assert limpar_cargo("[Remoto] Analista NOC - Telecom na Provedor B", "Provedor B") == "Analista NOC - Telecom"
    assert limpar_cargo("Técnico de TI (Híbrido)") == "Técnico de TI"


# ---------- Candidatura semiautomática ----------
import sqlite3


def test_banco_antigo_ganha_colunas_novas(tmp_path):
    caminho = str(tmp_path / "antigo.db")
    con = sqlite3.connect(caminho)
    con.execute("CREATE TABLE vagas (chave TEXT PRIMARY KEY, fonte TEXT, titulo TEXT, empresa TEXT, "
                "url TEXT, emails TEXT, encontrada_em TEXT, status TEXT DEFAULT 'nova', nota INTEGER, analise TEXT)")
    con.execute("INSERT INTO vagas (chave, titulo, emails, status, nota) VALUES ('g:1','Antiga','','nova',70)")
    con.commit(); con.close()
    b = Banco(caminho)
    assert b.fila_candidaturas()[0]["titulo"] == "Antiga"


def _banco_com_fila(tmp_path):
    b = Banco(str(tmp_path / "h.db"))
    for i, (titulo, nota) in enumerate([("Suporte N2", 90), ("Técnico de TI", 75), ("Infra AWS", 66)]):
        v = Vaga("gupy", str(i), titulo, empresa=f"Empresa {i}", url=f"https://x/{i}", descricao="ITIL, redes")
        b.registrar_vaga(v)
        b.salvar_analise(v.chave, nota, "bom perfil | A favor: ITIL; Zabbix | Lacunas: AWS", True)
    return b


def test_fluxo_candidatar(tmp_path, monkeypatch):
    from enviador import candidatura as c
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(c, "copiar", lambda t: True)
    b = _banco_com_fila(tmp_path)
    abertos, respostas = [], iter(["c", "z", "d", "x"])
    c.executar(b, "cv", CONFIG, entrada=lambda _: next(respostas), abrir=abertos.append)
    assert abertos == ["https://x/0", "https://x/1", "https://x/2"]       # maior nota primeiro
    status = {r["titulo"]: r["status"] for r in b.con.execute("SELECT titulo, status FROM vagas")}
    assert status == {"Suporte N2": "candidatei", "Técnico de TI": "depois", "Infra AWS": "descartada"}
    assert [r["titulo"] for r in b.fila_candidaturas()] == ["Técnico de TI"]   # adiada volta para a fila
    ficha = (tmp_path / "candidaturas" / "Empresa 0 - Suporte N2.txt").read_text(encoding="utf-8")
    assert "POR QUE VOCÊ QUER ESTA VAGA" in ficha and "- AWS" in ficha and "https://x/0" in ficha


def test_sair_no_meio_mantem_o_resto(tmp_path, monkeypatch):
    from enviador import candidatura as c
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(c, "copiar", lambda t: False)
    b = _banco_com_fila(tmp_path)
    c.executar(b, "cv", CONFIG, entrada=lambda _: "s", abrir=lambda u: None)
    assert len(b.fila_candidaturas()) == 3


def test_nome_arquivo_seguro_no_windows():
    from enviador.candidatura import nome_arquivo
    v = Vaga("g", "1", "TÉCNICO DE SUPORTE (TI) P/203- TIC - RS", empresa="Wyn:tech")
    assert not any(ch in nome_arquivo(v) for ch in '<>:"/\\|?*')
