"""Testes de configuração, vaga manual, reanálise, entrevista, currículo, resultados e painel."""
from datetime import datetime, timedelta
import os

import pytest
import yaml

from enviador import configuracao, ia
from enviador.banco import Banco
from enviador.modelos import Vaga

CONFIG = configuracao.completar(yaml.safe_load(open("config.example.yaml", encoding="utf-8")))
CV = ("Analista de suporte N2 com ITIL, Active Directory, Zabbix, Grafana, Linux, redes, "
      "impressoras e gestão de chamados. Atendimento a usuários e PDV. " * 3)
DESC = "Atendimento N2, ITIL, Active Directory, Windows Server, Office 365, impressoras e redes TCP/IP."


@pytest.fixture(autouse=True)
def sem_chave(monkeypatch):
    """Nenhum teste fala com a Anthropic de verdade."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def _vaga(b, i, titulo="Analista de Suporte", nota=80, status=None, fonte="gupy", etapa=None, dias=0, remoto=False):
    v = Vaga(fonte, str(i), titulo, empresa=f"Empresa {i}", url=f"https://x/{i}", descricao=DESC, remoto=remoto)
    b.registrar_vaga(v)
    b.salvar_analise(v.chave, nota, "ok", nota >= 65, ["Windows Server"], ["ITIL"], "ia")
    if status:
        b.marcar(v.chave, status)
    if etapa and etapa != "candidatei":
        b.registrar_etapa(v.chave, etapa)
    if dias:
        q = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
        b.con.execute("UPDATE vagas SET etapa_em=? WHERE chave=?", (q, v.chave))
        b.con.commit()
    return v


# ---------- configuração ----------
def test_config_ida_e_volta_mantem_tudo():
    c = configuracao.padrao()
    c["candidato"].update(nome="Ana", resumo="Linha um com: dois pontos e \"aspas\".", email="a@b.com")
    c["busca"]["palavras_chave"] = ["vendedora", "atendente: loja"]
    c["mensagem"]["modelo"] = "Olá {nome}!\n\nLinha com # e : dois pontos\n"
    c["extra_da_pessoa"] = {"x": 1}
    lido = yaml.safe_load(configuracao.renderizar(c))
    assert configuracao.completar(lido) == configuracao.completar(c)


def test_config_antiga_com_repositorios_dentro_de_fontes():
    antiga = {"busca": {"fontes": {"gupy": True, "github_vagas": True, "repositorios_github": ["a/b"]}}}
    c = configuracao.completar(antiga)
    assert c["busca"]["repositorios_github"] == ["a/b"]
    assert "repositorios_github" not in c["busca"]["fontes"]
    assert c["analise"]["nota_minima"] == 65                      # padrões preenchidos


def test_github_le_repositorios_no_formato_antigo(monkeypatch):
    from enviador import fontes
    chamados = []

    class R:
        def raise_for_status(self): pass
        def json(self): return []
    monkeypatch.setattr(fontes.requests, "get", lambda url, **k: chamados.append(url) or R())
    fontes.buscar_github({"busca": {"fontes": {"repositorios_github": ["qa-brasil/vagas"]}}}, ["qa"])
    assert chamados and "qa-brasil/vagas" in chamados[0]


def test_salvar_faz_copia_de_seguranca(tmp_path):
    caminho = tmp_path / "config.yaml"
    caminho.write_text("candidato:\n  nome: Antigo\n", encoding="utf-8")
    configuracao.salvar(configuracao.completar({"candidato": {"nome": "Novo"}}), caminho)
    assert "Antigo" in (tmp_path / "config.yaml.bak").read_text(encoding="utf-8")
    assert yaml.safe_load(caminho.read_text(encoding="utf-8"))["candidato"]["nome"] == "Novo"


def test_chave_do_config_vai_para_o_ambiente(tmp_path):
    from enviador.servico import carregar_config
    c = configuracao.completar(None)
    c["ia"]["chave_api"] = "sk-ant-xyz"
    configuracao.salvar(c, tmp_path / "config.yaml")
    carregar_config(str(tmp_path / "config.yaml"))
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-xyz" and ia.disponivel()


def test_config_com_erro_de_formatacao_explica(tmp_path):
    from enviador.servico import ErroConfig, carregar_config
    (tmp_path / "config.yaml").write_text("candidato:\n  nome: [quebrado\n", encoding="utf-8")
    with pytest.raises(ErroConfig, match="erro de formatação"):
        carregar_config(str(tmp_path / "config.yaml"))


def test_servidor_smtp_pelo_dominio():
    assert configuracao.servidor_smtp("x@gmail.com") == ("smtp.gmail.com", 587)
    assert configuracao.servidor_smtp("x@Hotmail.com")[0] == "smtp-mail.outlook.com"
    assert configuracao.servidor_smtp("x@empresa.com.br") is None


def test_testar_chave_recusa_formato_errado():
    assert ia.testar_chave("")[0] is False
    assert "sk-" in ia.testar_chave("abc123")[1]


def test_assistente_monta_config(tmp_path):
    pdf = tmp_path / "meu cv.pdf"
    pdf.write_bytes(b"%PDF fake")
    respostas = iter([
        "Ana Souza", "ana@gmail.com", "(51) 90000-0000", "",            # dados
        f'"{pdf}"',                                                      # currículo, com aspas do Windows
        "s",                                                             # aceitar sugestão da IA
        "", "Porto Alegre, Canoas", "s", "sênior",                       # cargos (sugeridos), cidades, remoto, excluir
        "s",                                                             # usar resumo sugerido
        "s", "", "n",                                                    # configurar e-mail, usuário = o mesmo, não testar
    ])
    senhas = iter(["sk-ant-boa", "senha-de-app"])
    cfg = configuracao.assistente(
        str(tmp_path / "config.yaml"), entrada=lambda _: next(respostas), senha=lambda _: next(senhas),
        saida=lambda *_: None, testar_ia=lambda c: (True, "ok"), ler_cv=lambda p: CV,
        sugerir=lambda cv: {"resumo": "Analista de suporte com ITIL.", "cargos": ["analista de suporte", "help desk"]})
    salvo = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert salvo["candidato"]["nome"] == "Ana Souza"
    assert salvo["candidato"]["curriculo_pdf"] == "curriculo.pdf" and (tmp_path / "curriculo.pdf").exists()
    assert salvo["busca"]["palavras_chave"] == ["analista de suporte", "help desk"]
    assert salvo["busca"]["cidades"] == ["Porto Alegre", "Canoas"]
    assert salvo["candidato"]["resumo"] == "Analista de suporte com ITIL."
    assert salvo["ia"]["chave_api"] == "sk-ant-boa"
    assert salvo["smtp"] == {"servidor": "smtp.gmail.com", "porta": 587, "usuario": "ana@gmail.com", "senha": "senha-de-app"}
    assert cfg["busca"]["aceitar_remoto"] is True


# ---------- vaga manual e reanálise ----------
def test_adicionar_vaga_manual_entra_na_fila_mesmo_com_nota_baixa(tmp_path):
    from enviador.servico import ErroVaga, adicionar_vaga
    b = Banco(str(tmp_path / "h.db"))
    r, nova = adicionar_vaga(CONFIG, b, "Vendedor externo", "Prospecção de clientes, metas de vendas, CNH B, "
                             "negociação e pós-venda em campo.", "Loja Z",
                             "https://www.infojobs.com.br/vaga-123.aspx", cv=CV)
    assert nova and r["status"] == "nova" and r["fonte"] == "manual:infojobs" and r["nota"] < 65
    r2, nova2 = adicionar_vaga(CONFIG, b, "Vendedor externo", "x" * 50, url="https://www.infojobs.com.br/vaga-123.aspx", cv=CV)
    assert not nova2 and r2["id"] == r["id"]
    with pytest.raises(ErroVaga):
        adicionar_vaga(CONFIG, b, "Cargo", "curta", cv=CV)
    with pytest.raises(ErroVaga):
        adicionar_vaga(CONFIG, b, "", DESC, cv=CV)


def test_reanalisar_mantem_adiada_e_exige_chave(tmp_path, monkeypatch):
    from enviador import servico
    from enviador.analise import Analise
    b = Banco(str(tmp_path / "h.db"))
    for i, st in enumerate(["nova", "depois", "baixa"]):
        v = Vaga("gupy", str(i), f"Vaga {i}", descricao=DESC)
        b.registrar_vaga(v)
        b.salvar_analise(v.chave, 70 if st != "baixa" else 30, "palavras", st != "baixa", metodo="palavras")
        if st == "depois":
            b.marcar(v.chave, "depois")
    with pytest.raises(servico.ErroConfig):
        servico.reanalisar(CONFIG, b, CV)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    notas = {"Vaga 0": 40, "Vaga 1": 85, "Vaga 2": 78}
    monkeypatch.setattr(servico, "analisar_vagas", lambda vs, cv, cfg: [
        (v, Analise(notas[v.titulo], notas[v.titulo] >= 65, "ia", [], [], "ia")) for v in vs])
    r = servico.reanalisar(CONFIG, b, CV)
    st = {x["titulo"]: x["status"] for x in b.listar()}
    assert st == {"Vaga 0": "baixa", "Vaga 1": "depois", "Vaga 2": "nova"}
    assert r == {"analisadas": 3, "recomendadas": 2, "mudaram": 2}
    assert servico.reanalisar(CONFIG, b, CV)["analisadas"] == 0        # nada mais por palavras


# ---------- entrevista ----------
def test_entrevista_roteiro_usa_lacunas_e_guarda(tmp_path):
    from enviador import entrevista
    b = Banco(str(tmp_path / "h.db"))
    v = _vaga(b, 1, status="candidatei")
    p = entrevista.preparo_do_banco(b, b.vaga(v.chave), CV, CONFIG)
    perguntas = [q["pergunta"] for q in p["perguntas"]]
    assert p["metodo"] == "roteiro"
    assert "Você tem experiência com Windows Server?" in perguntas
    assert any("na empresa Empresa 1" in q for q in perguntas)
    assert b.vaga(v.chave)["preparo"]                                   # guardado
    assert "PERGUNTAS PARA VOCÊ FAZER" in entrevista.texto(b.vaga(v.chave), p)


def test_entrevista_com_ia(tmp_path, monkeypatch):
    from enviador import entrevista
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    monkeypatch.setattr(ia, "pedir_json", lambda *a, **k: {
        "perguntas": [{"pergunta": "Como prioriza chamados?", "motivo": "SLA", "como_responder": "ITIL na Panvel"}],
        "para_perguntar": ["Volume de chamados?"], "pesquisar": ["Glassdoor"]})
    b = Banco(str(tmp_path / "h.db"))
    v = _vaga(b, 1)
    p = entrevista.preparar(b.vaga(v.chave), CV, CONFIG)
    assert p["metodo"] == "ia" and p["perguntas"][0]["pergunta"] == "Como prioriza chamados?"
    monkeypatch.setattr(ia, "pedir_json", lambda *a, **k: {"perguntas": []})
    assert entrevista.preparar(b.vaga(v.chave), CV, CONFIG)["metodo"] == "roteiro"   # cai no roteiro


# ---------- currículo e raio-x ----------
def test_sugestoes_de_curriculo(tmp_path):
    from enviador import curriculo, raiox
    b = Banco(str(tmp_path / "h.db"))
    for i in range(6):
        _vaga(b, i, titulo="Analista de Service Desk")
    vagas = b.vagas_analisadas()
    cfg = dict(CONFIG, busca=dict(CONFIG["busca"], palavras_chave=["service desk"]),
               candidato=dict(CONFIG["candidato"], linkedin=""))
    s = curriculo.sugestoes_regras(CV, raiox.calcular(vagas, CV, cfg), cfg, vagas)
    titulos = " | ".join(x["titulo"] for x in s)
    assert "Windows Server" in titulos and "Microsoft 365" in titulos      # pedem e falta
    assert '"service desk"' in titulos                                    # nome de cargo
    assert "números" in titulos and "LinkedIn" in titulos
    assert len([x for x in s if x["tipo"] == "incluir"]) <= 4


def test_raiox_outras_areas_e_filtro_por_area(tmp_path):
    from enviador.raiox import _compilar, habilidades_no_texto
    texto = "Vendedor com CRM Salesforce, prospecção, metas de vendas e Excel. NR-10 desejável."
    tudo = habilidades_no_texto(texto, _compilar())
    assert {"CRM (Salesforce, RD, HubSpot)", "Prospecção de clientes", "Metas de vendas", "Excel", "NR-10 (eletricidade)"} <= tudo
    so_comercial = habilidades_no_texto(texto, _compilar(areas=["comercial"]))
    assert "NR-10 (eletricidade)" not in so_comercial and "Excel" in so_comercial     # geral sempre vale
    assert "CRM ativo (médico)" in habilidades_no_texto("Médico com CRM ativo", _compilar())
    assert "CRM (Salesforce, RD, HubSpot)" not in habilidades_no_texto("Médico com CRM ativo", _compilar())


# ---------- resultados ----------
def test_resultados_com_poucos_dados_pede_paciencia(tmp_path):
    from enviador import aprendizado
    b = Banco(str(tmp_path / "h.db"))
    _vaga(b, 1, status="candidatei", etapa="entrevista")
    r = aprendizado.analisar(b, CONFIG)
    assert r["geral"]["avancaram"] == 1 and "Faltam 7" in r["sugestoes"][0]


def test_resultados_sugerem_subir_nota_minima(tmp_path):
    from enviador import aprendizado
    b = Banco(str(tmp_path / "h.db"))
    for i in range(5):
        _vaga(b, i, nota=68, status="candidatei", etapa="reprovado")
    for i in range(5, 9):
        _vaga(b, i, nota=90, status="candidatei", etapa="entrevista" if i % 2 else "reprovado")
    _vaga(b, 20, nota=88, status="candidatei", dias=30)            # parada há 30 dias = não avançou
    _vaga(b, 21, nota=88, status="candidatei", dias=2)             # recente = pendente
    r = aprendizado.analisar(b, CONFIG)
    assert r["geral"] == {"total": 11, "com_resultado": 10, "avancaram": 2, "taxa": 20}
    faixa = {f["faixa"]: f for f in r["faixas"]}
    assert faixa["65 a 74"]["taxa"] == 0 and faixa["85 ou mais"]["taxa"] == 40
    assert any("Subir a nota mínima para 75" in s for s in r["sugestoes"])
    assert r["fontes"][0]["fonte"] == "Gupy"


# ---------- painel ----------
@pytest.fixture
def painel(tmp_path):
    from enviador.painel import criar_app
    caminho = str(tmp_path / "h.db")
    b = Banco(caminho)
    _vaga(b, 1, nota=90)
    _vaga(b, 2, status="candidatei", etapa="entrevista")
    cfg = configuracao.completar(CONFIG)
    cfg["smtp"]["senha"] = "segredo"
    configuracao.salvar(cfg, tmp_path / "config.yaml")
    app = criar_app(cfg, caminho, cv=CV, caminho_config=str(tmp_path / "config.yaml"))
    return app.test_client(), tmp_path


def test_painel_adicionar_vaga(painel):
    c, _ = painel
    r = c.post("/api/vagas", json={"titulo": "Service Desk", "empresa": "E", "descricao": DESC,
                                   "url": "https://www.linkedin.com/jobs/1"}).get_json()
    assert r["manual"] and r["status"] == "nova" and not r["ja_existia"]
    assert c.post("/api/vagas", json={"titulo": "X", "descricao": "curta"}).status_code == 400
    assert any(v["titulo"] == "Service Desk" for v in c.get("/api/vagas?aba=fila").get_json())


def test_painel_config_nao_vaza_segredos_e_salva(painel):
    c, pasta = painel
    pub = c.get("/api/config").get_json()
    assert "senha" not in str(pub) or pub["smtp"]["tem_senha"] is True
    assert "segredo" not in str(pub)
    r = c.post("/api/config", json={"busca": {"palavras_chave": "suporte, help desk\nNOC", "dias_maximos": "20",
                                              "fontes": {"gupy": True, "adzuna": False}},
                                    "smtp": {"usuario": "novo@gmail.com", "senha": ""},
                                    "ia": {"chave_api": "sk-ant-nova"}})
    assert r.status_code == 200
    salvo = yaml.safe_load((pasta / "config.yaml").read_text(encoding="utf-8"))
    assert salvo["busca"]["palavras_chave"] == ["suporte", "help desk", "NOC"]
    assert salvo["busca"]["dias_maximos"] == 20
    assert salvo["smtp"]["senha"] == "segredo" and salvo["smtp"]["servidor"] == "smtp.gmail.com"   # senha vazia mantém
    assert salvo["ia"]["chave_api"] == "sk-ant-nova" and r.get_json()["ia"]["final"] == "nova"
    assert c.post("/api/config", json={"busca": {"palavras_chave": ""}}).status_code == 400
    assert c.post("/api/config", json={"analise": {"nota_minima": 5}}).status_code == 400
    assert c.post("/api/config", json={"busca": {"fontes": {"adzuna": True}}}).status_code == 400


def test_painel_entrevista_curriculo_resultados(painel):
    c, _ = painel
    cand = c.get("/api/vagas?aba=candidaturas").get_json()[0]
    p = c.get(f"/api/vagas/{cand['id']}/entrevista").get_json()
    assert p["metodo"] == "roteiro" and p["perguntas"]
    rx = c.get("/api/raiox").get_json()
    assert isinstance(rx["sugestoes"], list)
    assert c.post("/api/curriculo/ia").status_code == 400                 # sem chave
    assert c.get("/api/resultados").get_json()["geral"]["avancaram"] == 1
    resumo = c.get("/api/resumo").get_json()
    assert resumo["ia"] is False and resumo["configurado"] is True
    assert c.post("/api/reanalisar").status_code == 400
