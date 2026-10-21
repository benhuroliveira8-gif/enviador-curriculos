"""Testes do acompanhamento, follow-up, raio-x, Adzuna, rotina diária e painel."""
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import patch

import pytest
import yaml

from enviador.analise import Analise
from enviador.banco import Banco
from enviador.fontes import buscar_adzuna, filtrar
from enviador.modelos import Vaga

CONFIG = yaml.safe_load(open("config.example.yaml", encoding="utf-8"))
CV = ("Analista de suporte N2 com ITIL, Active Directory, Zabbix, Grafana, Linux, redes, "
      "impressoras e gestão de chamados. " * 3)


class Resp:
    def __init__(self, dados): self.dados = dados
    def raise_for_status(self): pass
    def json(self): return self.dados


def _vaga(b, i, titulo="Suporte N2", nota=80, status=None, desc="ITIL, Active Directory, Windows Server, AWS",
          lacunas=("Windows Server",)):
    v = Vaga("gupy", str(i), titulo, empresa=f"Empresa {i}", url=f"https://x/{i}", descricao=desc)
    b.registrar_vaga(v)
    b.salvar_analise(v.chave, nota, "ok", nota >= 65, list(lacunas), ["ITIL"], "ia")
    if status:
        b.marcar(v.chave, status)
    return v


def _envelhecer(b, chave, dias):
    q = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
    b.con.execute("UPDATE vagas SET etapa_em=? WHERE chave=?", (q, chave))
    b.con.commit()


# ---------- acompanhamento ----------
def test_candidatei_inicia_etapa_e_historico(tmp_path):
    b = Banco(str(tmp_path / "h.db"))
    v = _vaga(b, 1, status="candidatei")
    b.registrar_etapa(v.chave, "entrevista", "terça 14h")
    r = b.vaga(v.chave)
    assert r["etapa"] == "entrevista"
    assert [h["etapa"] for h in b.historico_etapas(v.chave)] == ["candidatei", "entrevista"]
    with pytest.raises(ValueError):
        b.registrar_etapa(v.chave, "festa")


def test_followup_so_para_ativas_paradas(tmp_path):
    b = Banco(str(tmp_path / "h.db"))
    parada = _vaga(b, 1, status="candidatei")
    recente = _vaga(b, 2, status="candidatei")
    encerrada = _vaga(b, 3, status="candidatei")
    b.registrar_etapa(encerrada.chave, "reprovado")
    for v in (parada, encerrada):
        _envelhecer(b, v.chave, 12)
    assert [r["titulo"] for r in b.followups(10)] == ["Suporte N2"]
    assert b.followups(10)[0]["chave"] == parada.chave
    b.marcar_followup(parada.chave)
    assert b.followups(10) == []                       # some depois de registrado
    assert recente.chave not in [r["chave"] for r in b.followups(10)]


def test_envio_por_email_conta_como_candidatura(tmp_path):
    b = Banco(str(tmp_path / "h.db"))
    v = _vaga(b, 1)
    b.registrar_envio(v.chave, "rh@x.com", True)
    assert b.vaga(v.chave)["etapa"] == "candidatei"
    assert len(b.candidaturas(so_ativas=True)) == 1


def test_banco_antigo_com_candidaturas_ganha_etapa(tmp_path):
    import sqlite3
    caminho = str(tmp_path / "a.db")
    con = sqlite3.connect(caminho)
    con.execute("CREATE TABLE vagas (chave TEXT PRIMARY KEY, fonte TEXT, titulo TEXT, empresa TEXT, url TEXT, "
                "emails TEXT, encontrada_em TEXT, status TEXT DEFAULT 'nova', nota INTEGER, analise TEXT)")
    con.execute("INSERT INTO vagas VALUES ('g:1','gupy','Antiga','E','u','','2026-10-01T10:00:00','candidatei',80,'')")
    con.commit(); con.close()
    assert Banco(caminho).vaga("g:1")["etapa"] == "candidatei"


# ---------- raio-x ----------
def test_raiox_separa_o_que_falta_do_que_tenho(tmp_path):
    from enviador import raiox
    b = Banco(str(tmp_path / "h.db"))
    for i in range(4):
        _vaga(b, i, nota=70 + i)
    _vaga(b, 9, titulo="Enfermeiro", nota=10, desc="COREN, plantões, AWS")     # outra área: não conta
    r = raiox.calcular(b.vagas_analisadas(), CV, CONFIG)
    faltam = {i.habilidade: i.percentual for i in r.faltam}
    tenho = {i.habilidade for i in r.tenho}
    assert r.total_area == 4
    assert faltam["Windows Server"] == 100 and faltam["AWS"] == 100
    assert {"ITIL", "Active Directory"} <= tenho
    assert r.lacunas_ia[0] == ("Windows Server", 4) and r.usou_ia


def test_raiox_junta_termo_quebrado_em_duas_linhas():
    from enviador.raiox import _compilar, habilidades_no_texto
    assert "Active Directory" in habilidades_no_texto("Identidade: Active\nDirectory", _compilar())


# ---------- filtros e Adzuna ----------
def test_filtro_ignora_acentos_e_duplicadas_entre_fontes():
    agora = datetime.now(timezone.utc)
    vs = [Vaga("gupy", "1", "Analista de Suporte", empresa="Acme", cidade="Guaíba", publicada_em=agora),
          Vaga("adzuna", "9", "Analista de suporte", empresa="ACME", cidade="Guaiba, Rio Grande do Sul", publicada_em=agora),
          Vaga("gupy", "2", "Analista Temporário", cidade="Porto Alegre", publicada_em=agora),
          Vaga("adzuna", "3", "Técnico de TI", empresa="B", cidade="Porto Alegre, Rio Grande do Sul", publicada_em=agora)]
    busca = {"cidades": ["Guaiba", "Porto Alegre"], "palavras_excluidas": ["temporario"]}
    assert [v.chave for v in filtrar(vs, busca)] == ["gupy:1", "adzuna:3"]


def test_adzuna_converte_resposta_e_exige_chave():
    assert buscar_adzuna({"busca": {"adzuna": {}}}, ["suporte"]) == []
    dados = {"results": [{"id": 77, "title": "Analista de <strong>Suporte</strong>",
                          "company": {"display_name": "Empresa Z"}, "location": {"display_name": "Porto Alegre, Rio Grande do Sul"},
                          "description": "Suporte N2 em regime home office. Currículo para vagas@z.com.br",
                          "redirect_url": "https://adzuna/77", "created": "2026-10-15T09:00:00Z"}]}
    cfg = {"busca": {"adzuna": {"app_id": "a", "app_key": "b", "onde": "Rio Grande do Sul"}, "dias_maximos": 15}}
    with patch("enviador.fontes.requests.get", return_value=Resp(dados)) as get:
        v = buscar_adzuna(cfg, ["suporte"])[0]
    params = get.call_args.kwargs["params"]
    assert params["where"] == "Rio Grande do Sul" and params["max_days_old"] == 15
    assert v.titulo == "Analista de Suporte" and v.remoto and v.emails == ["vagas@z.com.br"]
    assert v.chave == "adzuna:77" and v.empresa == "Empresa Z"


# ---------- rotina diária ----------
def _analise(nota):
    return Analise(nota=nota, recomendada=nota >= 65, resumo="bom", pontos_fortes=["ITIL"], lacunas=["AWS"], metodo="ia")


def test_diario_destaca_nota_alta_e_followup(tmp_path, monkeypatch):
    from enviador import diario, servico
    monkeypatch.chdir(tmp_path)
    b = Banco(str(tmp_path / "h.db"))
    antiga = _vaga(b, 50, status="candidatei")
    _envelhecer(b, antiga.chave, 15)
    novas = [Vaga("gupy", "1", "Suporte N2", empresa="A", url="u1", descricao="ITIL"),
             Vaga("gupy", "2", "Técnico", empresa="B", url="u2", descricao="ITIL")]
    monkeypatch.setattr(servico, "buscar_todas", lambda cfg: novas)
    monkeypatch.setattr(servico, "analisar_vagas", lambda vs, cv, cfg: [(vs[0], _analise(90)), (vs[1], _analise(70))])
    cfg = dict(CONFIG, smtp={"usuario": "eu@gmail.com", "senha": "x", "servidor": "s"})
    enviados = []
    with patch("enviador.remetente.enviar_aviso", lambda *a: enviados.append(a)):
        r = diario.executar(cfg, b, saida=lambda m: None, cv=CV)
    assert [v.titulo for v, _ in r.destaques] == ["Suporte N2"]      # só nota >= 75
    assert r.outras_recomendadas == 1 and len(r.followups) == 1
    assert enviados and enviados[0][1] == CONFIG["candidato"]["email"]
    assert "1 vaga com nota alta, 1 follow-up" in enviados[0][2]
    html = enviados[0][3]
    assert "Suporte N2" in html and "Hora de fazer follow-up" in html
    assert (tmp_path / "relatorios").glob("diario-*.html")


def test_diario_sem_novidade_nao_manda_email(tmp_path, monkeypatch):
    from enviador import diario, servico
    monkeypatch.chdir(tmp_path)
    b = Banco(str(tmp_path / "h.db"))
    monkeypatch.setattr(servico, "buscar_todas", lambda cfg: [])
    cfg = dict(CONFIG, smtp={"usuario": "eu@gmail.com", "senha": "x", "servidor": "s"})
    with patch("enviador.remetente.enviar_aviso") as env:
        r = diario.executar(cfg, b, saida=lambda m: None, cv=CV)
    assert not r.tem_novidade and not env.called


def test_diario_avisa_quando_a_busca_quebra(tmp_path, monkeypatch):
    from enviador import diario, servico
    monkeypatch.chdir(tmp_path)
    b = Banco(str(tmp_path / "h.db"))
    def quebra(cfg): raise ConnectionError("sem internet")
    monkeypatch.setattr(servico, "buscar_todas", quebra)
    r = diario.montar(CONFIG, b, cv=CV)
    assert "sem internet" in r.erro and r.tem_novidade


# ---------- painel ----------
@pytest.fixture
def cliente(tmp_path):
    from enviador.painel import criar_app
    caminho = str(tmp_path / "h.db")
    b = Banco(caminho)
    _vaga(b, 1, nota=90)
    _vaga(b, 2, nota=40)
    feita = _vaga(b, 3, status="candidatei")
    _envelhecer(b, feita.chave, 20)
    app = criar_app(CONFIG, caminho, cv=CV)
    return app.test_client()


def test_painel_lista_abas(cliente):
    assert cliente.get("/").status_code == 200
    r = cliente.get("/api/resumo").get_json()
    assert (r["fila"], r["candidaturas"], r["followups"], r["descartadas"]) == (1, 1, 1, 1)
    fila = cliente.get("/api/vagas?aba=fila").get_json()
    assert [v["nota"] for v in fila] == [90] and fila[0]["lacunas"] == ["Windows Server"]
    assert len(cliente.get("/api/vagas?aba=descartadas").get_json()) == 1


def test_painel_status_etapa_respostas_raiox(cliente):
    vid = cliente.get("/api/vagas?aba=fila").get_json()[0]["id"]
    assert cliente.post(f"/api/vagas/{vid}/status", json={"status": "candidatei"}).get_json()["etapa"] == "candidatei"
    assert cliente.post(f"/api/vagas/{vid}/etapa", json={"etapa": "teste", "obs": "online"}).get_json()["etapa"] == "teste"
    assert cliente.post(f"/api/vagas/{vid}/etapa", json={"etapa": "xyz"}).status_code == 400
    det = cliente.get(f"/api/vagas/{vid}").get_json()
    assert [h["etapa"] for h in det["historico"]] == ["candidatei", "teste"]
    resp = cliente.get(f"/api/vagas/{vid}/respostas").get_json()
    assert resp["por_que_vaga"] and cliente.get(f"/api/vagas/{vid}").get_json()["tem_respostas"]
    rx = cliente.get("/api/raiox").get_json()
    assert rx["total_area"] >= 2 and any(i["habilidade"] == "Windows Server" for i in rx["faltam"])
    assert cliente.get("/api/vagas/999").status_code == 404


def test_painel_followup(cliente):
    vid = cliente.get("/api/vagas?aba=followup").get_json()[0]["id"]
    cliente.post(f"/api/vagas/{vid}/followup")
    assert cliente.get("/api/vagas?aba=followup").get_json() == []
