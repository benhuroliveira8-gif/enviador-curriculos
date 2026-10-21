"""Fontes de vagas. Cada fonte devolve uma lista de Vaga.

Para adicionar uma nova fonte, crie uma função buscar_<nome>(config, palavras) -> list[Vaga]
e registre em FONTES no final do arquivo.
"""
from datetime import datetime, timezone
import logging
import re
import unicodedata

import requests

from .extrator import extrair_emails
from .modelos import Vaga

log = logging.getLogger(__name__)
TIMEOUT = 20
HEADERS = {"User-Agent": "enviador-curriculos/0.1"}


def _data(iso: str | None):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------- Gupy (portal público de vagas) ----------
# Endereço novo (o antigo portal.api.gupy.io/api/v1/jobs passou a responder 404).
GUPY_URL = "https://portal.gupy.io/api/job-search/jobs"


def buscar_gupy(config: dict, palavras: list[str]) -> list[Vaga]:
    vagas = []
    for termo in palavras:
        try:
            r = requests.get(GUPY_URL, params={"jobName": termo, "limit": 50},
                             headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            itens = r.json().get("data", [])
        except Exception as e:  # fonte fora do ar não deve derrubar o resto
            log.warning("Gupy falhou para '%s': %s", termo, e)
            continue
        for j in itens:
            descricao = j.get("description") or ""
            vagas.append(Vaga(
                fonte="gupy",
                id_externo=str(j.get("id")),
                titulo=j.get("name") or "",
                empresa=j.get("careerPageName") or "",
                descricao=descricao,
                url=j.get("jobUrl") or "",
                cidade=j.get("city") or "",
                remoto=bool(j.get("isRemoteWork")) or (j.get("workplaceType") or "").lower() == "remote",
                publicada_em=_data(j.get("publishedDate")),
                emails=extrair_emails(descricao),
            ))
    return vagas


# ---------- Repositórios de vagas no GitHub (comunidades brasileiras de tecnologia) ----------
def _empresa_do_titulo(titulo: str) -> str:
    # Títulos costumam ser "[Remoto] Dev Python na Empresa X" ou "Dev Python @ Empresa X"
    m = re.search(r"(?:\bna\b|\bno\b|@|\bpara\b)\s+([^\[\]\-|]+)$", titulo, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def buscar_github(config: dict, palavras: list[str]) -> list[Vaga]:
    busca = config.get("busca", {})
    headers = dict(HEADERS, Accept="application/vnd.github+json")
    if busca.get("github_token"):
        headers["Authorization"] = f"Bearer {busca['github_token']}"
    vagas = []
    for repo in busca.get("repositorios_github", []):
        try:
            r = requests.get(f"https://api.github.com/repos/{repo}/issues",
                             params={"state": "open", "per_page": 100},
                             headers=headers, timeout=TIMEOUT)
            r.raise_for_status()
            itens = r.json()
        except Exception as e:
            log.warning("GitHub falhou para %s: %s", repo, e)
            continue
        for i in itens:
            if "pull_request" in i:
                continue
            titulo = i.get("title", "")
            corpo = i.get("body") or ""
            texto = f"{titulo}\n{corpo}".lower()
            if palavras and not any(p.lower() in texto for p in palavras):
                continue
            rotulos = " ".join(l.get("name", "") for l in i.get("labels", [])).lower()
            vagas.append(Vaga(
                fonte=f"github:{repo}",
                id_externo=str(i.get("number")),
                titulo=titulo,
                empresa=_empresa_do_titulo(titulo),
                descricao=corpo,
                url=i.get("html_url", ""),
                remoto="remoto" in texto or "remote" in rotulos or "remoto" in rotulos,
                publicada_em=_data(i.get("created_at")),
                emails=extrair_emails(corpo),
            ))
    return vagas


# ---------- Adzuna (API oficial, agrega vagas de vários sites) ----------
# Cadastro gratuito em https://developer.adzuna.com para obter app_id e app_key.
ADZUNA_URL = "https://api.adzuna.com/v1/api/jobs/br/search/{pagina}"


def _sem_html(texto: str) -> str:
    return re.sub(r"<[^>]+>", "", texto or "").strip()


def buscar_adzuna(config: dict, palavras: list[str]) -> list[Vaga]:
    busca = config.get("busca", {})
    cfg = busca.get("adzuna", {}) or {}
    if not (cfg.get("app_id") and cfg.get("app_key")):
        log.warning("Adzuna ativada, mas sem app_id/app_key no config. Pulando.")
        return []
    onde = cfg.get("onde") or ""
    vagas = []
    for termo in palavras:
        params = {"app_id": cfg["app_id"], "app_key": cfg["app_key"], "what": termo,
                  "results_per_page": 50, "content-type": "application/json"}
        if onde:
            params["where"] = onde
        if busca.get("dias_maximos"):
            params["max_days_old"] = busca["dias_maximos"]
        try:
            r = requests.get(ADZUNA_URL.format(pagina=1), params=params, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            itens = r.json().get("results", [])
        except Exception as e:
            log.warning("Adzuna falhou para '%s': %s", termo, e)
            continue
        for j in itens:
            descricao = _sem_html(j.get("description"))
            titulo = _sem_html(j.get("title"))
            texto = f"{titulo} {descricao}".lower()
            vagas.append(Vaga(
                fonte="adzuna",
                id_externo=str(j.get("id")),
                titulo=titulo,
                empresa=_sem_html((j.get("company") or {}).get("display_name")),
                descricao=descricao,
                url=j.get("redirect_url") or "",
                cidade=(j.get("location") or {}).get("display_name") or "",
                remoto=any(t in texto for t in ("remoto", "home office", "remote", "teletrabalho")),
                publicada_em=_data(j.get("created")),
                emails=extrair_emails(descricao),
            ))
    return vagas


FONTES = {
    "gupy": buscar_gupy,
    "github_vagas": buscar_github,
    "adzuna": buscar_adzuna,
}


def buscar_todas(config: dict) -> list[Vaga]:
    busca = config.get("busca", {})
    palavras = busca.get("palavras_chave", [])
    ativas = busca.get("fontes", {})
    vagas = []
    for nome, func in FONTES.items():
        if ativas.get(nome):
            encontradas = func(config, palavras)
            log.info("%s: %d vagas", nome, len(encontradas))
            vagas.extend(encontradas)
    return filtrar(vagas, busca)


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").lower()).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip()


def filtrar(vagas: list[Vaga], busca: dict) -> list[Vaga]:
    excluir = [_norm(p) for p in busca.get("palavras_excluidas", [])]
    cidades = [_norm(c) for c in busca.get("cidades", [])]
    dias = busca.get("dias_maximos")
    agora = datetime.now(timezone.utc)
    vistas, resultado = set(), []
    for v in vagas:
        # a mesma vaga pode vir de duas fontes (ex.: Gupy e Adzuna): fica a primeira
        assinatura = (_norm(v.titulo), _norm(v.empresa))
        if v.chave in vistas or (v.empresa and assinatura in vistas):
            continue
        vistas.update({v.chave, assinatura})
        titulo = _norm(v.titulo)
        if any(re.search(rf"\b{re.escape(p)}\b", titulo) for p in excluir):
            continue
        cidade = _norm(v.cidade)
        if cidades and not (v.remoto and busca.get("aceitar_remoto", True)) \
                and not any(c == cidade or cidade.startswith(c + ",") or cidade.startswith(c + " -")
                            for c in cidades):
            continue
        if dias and v.publicada_em and (agora - v.publicada_em).days > dias:
            continue
        resultado.append(v)
    return resultado
