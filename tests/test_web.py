"""Testes do site público (envie o currículo, veja as vagas)."""
from datetime import datetime, timezone
import io

import pytest

from enviador import web
from enviador.analise import Analise
from enviador.modelos import Vaga

TEXTO_CV = ("Analista de suporte N2 com ITIL, Active Directory, Zabbix e redes. Objetivo: analista de suporte. "
            "Experiência como analista de suporte e help desk em varejo. " * 4)
AGORA = datetime.now(timezone.utc)


def _vagas(cfg, termos):
    return [Vaga("gupy", str(i), t, empresa=f"E{i}", cidade=c, remoto=r, url=f"https://x/{i}",
                 descricao="ITIL, Active Directory, redes, Windows Server", publicada_em=AGORA)
            for i, (t, c, r) in enumerate([("Analista de Suporte N2", "Porto Alegre", False),
                                            ("Help Desk", "", True),
                                            ("Analista de Suporte", "Curitiba", False),
                                            ("Enfermeiro", "Porto Alegre", False)])]


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setattr(web, "ler_pdf", lambda dados: TEXTO_CV if dados.startswith(b"%PDF") else (_ for _ in ()).throw(web.ErroEnvio("O arquivo precisa ser um PDF.")))
    chamadas = []
    monkeypatch.setattr(web.fontes, "buscar_gupy", lambda cfg, termos: chamadas.append(termos[0]) or _vagas(cfg, termos))
    app = web.criar_app(limites=web.Limites(2, 1), rodar_em_segundo_plano=False)
    c = app.test_client()
    c.chamadas = chamadas
    return c


def _enviar(c, **campos):
    dados = {"aceite": "1", "cidade": "Porto Alegre", "remoto": "1", "cargos": "",
             "curriculo": (io.BytesIO(b"%PDF-1.4 fake"), "cv.pdf")}
    dados.update(campos)
    return c.post("/api/analisar", data=dados, content_type="multipart/form-data")


def test_paginas_abrem(cliente):
    assert cliente.get("/").status_code == 200
    assert "Como usamos os seus dados" in cliente.get("/privacidade").get_data(as_text=True)
    assert cliente.get("/saude").get_data(as_text=True) == "ok"


def test_fluxo_sem_ia_descobre_cargo_pelo_texto(cliente):
    r = _enviar(cliente)
    assert r.status_code == 200
    job = cliente.get(f"/api/analisar/{r.get_json()['id']}").get_json()
    assert job["etapa"] == "pronto" and job["usou_ia"] is False
    assert "analista de suporte" in job["perfil"]["cargos"]
    titulos = [v["titulo"] for v in job["vagas"]]
    assert "Analista de Suporte" not in titulos             # Curitiba ficou de fora pelo filtro de cidade
    assert "Help Desk" in titulos                           # remota entra
    assert all(v["nota"] >= web.NOTA_MINIMA_MOSTRAR for v in job["vagas"])
    assert "Enfermeiro" not in titulos                      # nota baixa não aparece
    assert "texto" not in str(job) and "ITIL, Active Directory, Zabbix" not in str(job)   # o currículo não fica


def test_cache_evita_buscar_duas_vezes(cliente):
    _enviar(cliente, cargos="help desk")
    _enviar(cliente, cargos="help desk")
    assert cliente.chamadas == ["help desk"]


def test_validacoes_e_limite(cliente):
    assert "confirme" in _enviar(cliente, aceite="").get_json()["erro"]
    assert "PDF" in _enviar(cliente, curriculo=(io.BytesIO(b"\x89PNG"), "foto.png")).get_json()["erro"]
    assert _enviar(cliente).status_code == 200
    assert _enviar(cliente).status_code == 200
    r = _enviar(cliente)
    assert r.status_code == 429 and "2 análises hoje" in r.get_json()["erro"]


def test_resultado_expirado(cliente):
    assert cliente.get("/api/analisar/naoexiste").status_code == 404


def test_com_ia_e_limite_diario_de_ia(cliente, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    monkeypatch.setattr(web, "sugerir_perfil", lambda cv: {"resumo": "Suporte de TI.", "cargos": ["analista de suporte"]})
    notas = {"Analista de Suporte N2": 90, "Help Desk": 70, "Enfermeiro": 10}
    modelos = []

    def falsa(cv, v, cand, modelo=None):
        modelos.append(modelo)
        return Analise(notas[v.titulo], True, "ok", ["ITIL"], ["Windows Server"], "ia")
    monkeypatch.setattr(web, "analisar_com_ia", falsa)
    job = cliente.get(f"/api/analisar/{_enviar(cliente).get_json()['id']}").get_json()
    assert job["usou_ia"] and job["perfil"]["resumo"] == "Suporte de TI."
    assert [v["nota"] for v in job["vagas"]] == [90, 70] and job["abaixo"] == 1
    assert set(modelos) == {web.ia.MODELO_RAPIDO}
    # a cota de IA do dia (1) acabou: a segunda análise sai por palavras e avisa
    job2 = cliente.get(f"/api/analisar/{_enviar(cliente).get_json()['id']}").get_json()
    assert job2["usou_ia"] is False and job2["ia_esgotada"] is True


def test_sem_ia_e_sem_cargo_reconhecivel_pede_cargos(cliente, monkeypatch):
    monkeypatch.setattr(web, "ler_pdf", lambda d: "Texto genérico sem nenhum cargo conhecido. " * 10)
    r = _enviar(cliente)
    assert r.status_code == 400 and "cargos" in r.get_json()["erro"]


def test_cargos_pelo_texto_ignora_emprego_antigo():
    texto = ("Objetivo: atuar como analista de suporte. Analista de suporte na empresa A. " * 2
             + "x " * 400 + "Eletricista em 2019.")
    assert web.cargos_pelo_texto(texto) == ["analista de suporte"]


def test_ler_pdf_recusa_arquivo_que_nao_e_pdf():
    with pytest.raises(web.ErroEnvio):
        web.ler_pdf(b"isso nao e pdf")
