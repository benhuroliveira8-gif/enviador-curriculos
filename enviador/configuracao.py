"""Configuração: valores padrão, gravação do config.yaml e assistente interativo.

`python -m enviador configurar` faz perguntas e monta o config.yaml sem ninguém editar YAML.
O painel também grava por aqui. Antes de sobrescrever, uma cópia fica em config.yaml.bak.
"""
import copy
import getpass
import json
import shutil
import smtplib
import subprocess
import sys
import textwrap
from pathlib import Path

import yaml

MODELO_MENSAGEM = """Olá, equipe de recrutamento{empresa_frase}!

Vi a vaga de {cargo} e gostaria de me candidatar. {resumo}

Envio meu currículo em anexo e fico à disposição para uma conversa.

Atenciosamente,
{nome}
{telefone}
"""


def padrao() -> dict:
    return {
        "candidato": {"nome": "", "email": "", "telefone": "", "linkedin": "",
                      "curriculo_pdf": "curriculo.pdf", "pretensao_salarial": "", "resumo": ""},
        "busca": {
            "palavras_chave": [], "palavras_excluidas": ["sênior", "senior", "estágio", "estagiário"],
            "cidades": [], "aceitar_remoto": True, "dias_maximos": 15,
            "fontes": {"gupy": True, "adzuna": False, "github_vagas": False},
            "repositorios_github": ["backend-br/vagas", "frontendbr/vagas", "react-brasil/vagas", "qa-brasil/vagas"],
            "github_token": "",
            "adzuna": {"app_id": "", "app_key": "", "onde": ""},
        },
        "analise": {"usar_ia": True, "nota_minima": 65, "nota_minima_pre_filtro": 25, "max_analises_ia": 30},
        "ia": {"chave_api": ""},
        "envio": {"modo_teste": True, "max_por_dia": 15, "intervalo_segundos": [60, 180], "copia_para_mim": True,
                  "empresas_bloqueadas": [], "automatico_no_diario": False},
        "smtp": {"servidor": "smtp.gmail.com", "porta": 587, "usuario": "", "senha": ""},
        "aviso": {"email": True, "para": "", "nota_alerta": 75, "enviar_sem_novidades": False},
        "acompanhamento": {"dias_followup": 10},
        "raiox": {"nota_minima_area": 30, "areas": [], "habilidades_extras": {}},
        "mensagem": {"usar_ia": True, "assunto": "Candidatura - {cargo} - {nome}", "modelo": MODELO_MENSAGEM},
    }


def completar(cfg: dict | None) -> dict:
    """Preenche o que faltar com os padrões, sem mexer no que a pessoa definiu."""
    base = padrao()
    cfg = copy.deepcopy(cfg or {})
    # configs antigos guardavam a lista de repositórios dentro de busca.fontes
    fontes = (cfg.get("busca") or {}).get("fontes") or {}
    if "repositorios_github" in fontes:
        cfg["busca"].setdefault("repositorios_github", fontes.pop("repositorios_github"))

    def mesclar(a: dict, b: dict) -> dict:
        for k, v in b.items():
            if isinstance(v, dict) and isinstance(a.get(k), dict):
                a[k] = mesclar(a[k], v)
            else:
                a[k] = v
        return a
    return mesclar(base, cfg)


# ---------- gravação ----------
def _j(v) -> str:
    """Valor YAML numa linha (JSON é YAML válido)."""
    return json.dumps(v, ensure_ascii=False)


def _dobrado(texto: str, recuo: int) -> str:
    texto = " ".join((texto or "").split())
    if not texto:
        return '""'
    linhas = textwrap.wrap(texto, 88)
    return ">-\n" + "\n".join(" " * recuo + l for l in linhas)


def _bloco(texto: str, recuo: int) -> str:
    texto = (texto or "").rstrip("\n")
    if not texto:
        return '""'
    return "|\n" + "\n".join((" " * recuo + l) if l else "" for l in texto.split("\n"))


def renderizar(cfg: dict) -> str:
    c = completar(cfg)
    ca, b, an, en, sm, av, ac, rx, me = (c[k] for k in
                                          ("candidato", "busca", "analise", "envio", "smtp", "aviso",
                                           "acompanhamento", "raiox", "mensagem"))
    f, az = b["fontes"], b["adzuna"]
    texto = f"""# Configuração do Enviador de Currículos.
# Dá para editar por aqui, pelo painel (aba Configurações) ou com: python -m enviador configurar
# NUNCA compartilhe este arquivo: ele guarda senha de e-mail e chave da IA.

candidato:
  nome: {_j(ca["nome"])}
  email: {_j(ca["email"])}
  telefone: {_j(ca["telefone"])}
  linkedin: {_j(ca["linkedin"])}
  curriculo_pdf: {_j(ca["curriculo_pdf"])}          # seu currículo em PDF, nesta pasta
  pretensao_salarial: {_j(ca["pretensao_salarial"])}     # opcional; aparece nas fichas de candidatura
  resumo: {_dobrado(ca["resumo"], 4)}

busca:
  palavras_chave: {_j(b["palavras_chave"])}     # cargos que você procura
  palavras_excluidas: {_j(b["palavras_excluidas"])}     # vagas com estes termos no título são ignoradas
  cidades: {_j(b["cidades"])}     # vazio = qualquer lugar
  aceitar_remoto: {_j(b["aceitar_remoto"])}
  dias_maximos: {_j(b["dias_maximos"])}     # ignora vagas publicadas há mais tempo
  fontes:
    gupy: {_j(f["gupy"])}     # vagas de todas as áreas
    adzuna: {_j(f["adzuna"])}     # agrega vários sites; precisa de app_id e app_key (abaixo)
    github_vagas: {_j(f["github_vagas"])}     # repositórios de vagas de programação; muitas trazem e-mail
  repositorios_github: {_j(b["repositorios_github"])}
  github_token: {_j(b["github_token"])}     # opcional; aumenta o limite de consultas ao GitHub
  adzuna:     # cadastro gratuito em https://developer.adzuna.com
    app_id: {_j(az["app_id"])}
    app_key: {_j(az["app_key"])}
    onde: {_j(az["onde"])}     # região da busca na Adzuna; vazio = Brasil todo

analise:
  usar_ia: {_j(an["usar_ia"])}     # análise com IA (precisa da chave em ia.chave_api)
  nota_minima: {_j(an["nota_minima"])}     # vagas com nota a partir daqui são recomendadas (0 a 100)
  nota_minima_pre_filtro: {_j(an["nota_minima_pre_filtro"])}     # abaixo disso a vaga nem vai para a IA
  max_analises_ia: {_j(an["max_analises_ia"])}     # máximo de vagas analisadas pela IA por busca

ia:
  chave_api: {_j(c["ia"]["chave_api"])}     # chave da Anthropic (console.anthropic.com); começa com sk-

envio:
  modo_teste: {_j(en["modo_teste"])}     # true = candidatura por e-mail só mostra o que enviaria
  max_por_dia: {_j(en["max_por_dia"])}
  intervalo_segundos: {_j(en["intervalo_segundos"])}     # espera aleatória entre envios
  copia_para_mim: {_j(en["copia_para_mim"])}
  empresas_bloqueadas: {_j(en["empresas_bloqueadas"])}     # nunca enviar para estas empresas
  automatico_no_diario: {_j(en["automatico_no_diario"])}     # true = a rotina diária também envia candidaturas por e-mail

smtp:     # conta que envia os e-mails. Gmail: use uma "senha de app"
  servidor: {_j(sm["servidor"])}
  porta: {_j(sm["porta"])}
  usuario: {_j(sm["usuario"])}
  senha: {_j(sm["senha"])}

aviso:     # resumo diário por e-mail
  email: {_j(av["email"])}
  para: {_j(av["para"])}     # vazio = o seu e-mail do bloco candidato
  nota_alerta: {_j(av["nota_alerta"])}     # vagas com nota a partir daqui viram destaque
  enviar_sem_novidades: {_j(av["enviar_sem_novidades"])}

acompanhamento:
  dias_followup: {_j(ac["dias_followup"])}     # lembrete de follow-up após tantos dias sem novidade

raiox:
  nota_minima_area: {_j(rx["nota_minima_area"])}     # vagas abaixo disso são de outra área
  areas: {_j(rx["areas"])}     # vazio = todas; ex.: ["ti", "administrativo"]
  habilidades_extras: {_j(rx["habilidades_extras"])}     # ex.: {{"Fortinet NSE": ["fortinet", "nse ?[1-4]"]}}

mensagem:
  usar_ia: {_j(me["usar_ia"])}     # respostas e e-mails escritos sob medida pela IA
  assunto: {_j(me["assunto"])}
  modelo: {_bloco(me["modelo"], 4)}
"""
    extras = {k: v for k, v in (cfg or {}).items() if k not in padrao()}
    if extras:
        texto += "\n# Outras opções\n" + yaml.safe_dump(extras, allow_unicode=True, sort_keys=False)
    return texto


def salvar(cfg: dict, caminho: str | Path = "config.yaml") -> Path:
    caminho = Path(caminho)
    texto = renderizar(cfg)
    yaml.safe_load(texto)                      # garante que o arquivo novo é válido antes de gravar
    if caminho.exists():
        shutil.copy2(caminho, caminho.with_name(caminho.name + ".bak"))
    caminho.write_text(texto, encoding="utf-8")
    return caminho


def servidor_smtp(email: str) -> tuple[str, int] | None:
    dominio = (email or "").rsplit("@", 1)[-1].lower()
    if dominio in ("gmail.com", "googlemail.com"):
        return "smtp.gmail.com", 587
    if dominio in ("hotmail.com", "outlook.com", "live.com", "msn.com", "outlook.com.br", "hotmail.com.br"):
        return "smtp-mail.outlook.com", 587
    if dominio in ("yahoo.com", "yahoo.com.br"):
        return "smtp.mail.yahoo.com", 587
    return None


def testar_smtp(smtp: dict) -> tuple[bool, str]:
    try:
        con = smtplib.SMTP(smtp["servidor"], int(smtp.get("porta", 587)), timeout=20)
        con.starttls()
        con.login(smtp["usuario"], smtp["senha"])
        con.quit()
        return True, "Login no e-mail funcionando."
    except smtplib.SMTPAuthenticationError:
        dica = (" No Gmail, use uma senha de app (Conta Google → Segurança → Senhas de app)."
                if "gmail" in smtp.get("servidor", "") else
                " Contas pessoais Hotmail/Outlook costumam bloquear esse tipo de acesso; um Gmail com senha de app funciona melhor.")
        return False, "O servidor recusou usuário ou senha." + dica
    except Exception as e:  # noqa: BLE001
        return False, f"Não consegui conectar ao servidor de e-mail: {e}"


# ---------- assistente ----------
def _lista(texto: str) -> list[str]:
    return [p.strip() for p in (texto or "").replace(";", ",").split(",") if p.strip()]


class Assistente:
    def __init__(self, entrada=input, senha=getpass.getpass, saida=print):
        self.entrada, self.senha, self.saida = entrada, senha, saida

    def perguntar(self, texto: str, atual="") -> str:
        mostrar = ", ".join(atual) if isinstance(atual, list) else atual
        sufixo = f" [{mostrar}]" if mostrar not in ("", None) else ""
        r = self.entrada(f"{texto}{sufixo}: ").strip()
        return r if r else (atual if not isinstance(atual, list) else ", ".join(atual))

    def sim(self, texto: str, padrao_sim: bool = True) -> bool:
        r = self.entrada(f"{texto} [{'S/n' if padrao_sim else 's/N'}]: ").strip().lower()
        return padrao_sim if not r else r.startswith("s")

    def numero(self, texto: str, atual: int, minimo: int, maximo: int) -> int:
        while True:
            r = self.entrada(f"{texto} [{atual}]: ").strip()
            if not r:
                return atual
            if r.isdigit() and minimo <= int(r) <= maximo:
                return int(r)
            self.saida(f"  Digite um número entre {minimo} e {maximo}.")


def assistente(caminho: str = "config.yaml", entrada=input, senha=getpass.getpass, saida=print,
               testar_ia=None, testar_email=None, ler_cv=None, sugerir=None) -> dict:
    from . import ia
    a = Assistente(entrada, senha, saida)
    testar_ia = testar_ia or ia.testar_chave
    testar_email = testar_email or testar_smtp
    if ler_cv is None:
        from .analise import ler_curriculo as ler_cv
    existente = Path(caminho).exists()
    cfg = completar(yaml.safe_load(Path(caminho).read_text(encoding="utf-8")) if existente else None)
    ca, b = cfg["candidato"], cfg["busca"]

    saida("\nVamos configurar o enviador. Aperte Enter para manter o valor entre colchetes.\n")

    saida("— Seus dados —")
    ca["nome"] = a.perguntar("Nome completo", ca["nome"])
    ca["email"] = a.perguntar("Seu e-mail (para onde os recrutadores respondem)", ca["email"])
    ca["telefone"] = a.perguntar("Telefone com DDD", ca["telefone"])
    ca["linkedin"] = a.perguntar("Link do LinkedIn (opcional)", ca["linkedin"])

    saida("\n— Currículo —")
    cv_texto = ""
    while True:
        bruto = a.perguntar("Caminho do seu currículo em PDF", ca["curriculo_pdf"]).strip().strip('"').strip("'")
        p = Path(bruto).expanduser()
        if not p.exists():
            saida(f"  Não encontrei {p}. Dica: no Explorador, clique com o botão direito no PDF → 'Copiar como caminho'.")
            continue
        destino = Path(caminho).with_name("curriculo.pdf")
        if p.resolve() != destino.resolve():
            shutil.copy2(p, destino)
            saida(f"  Copiei o currículo para {destino.name} nesta pasta.")
        ca["curriculo_pdf"] = "curriculo.pdf"
        try:
            cv_texto = ler_cv(str(destino))
        except Exception as e:  # noqa: BLE001
            saida(f"  Não consegui ler o PDF ({e}). Ele precisa ser um PDF de texto, não uma foto.")
            continue
        if len(cv_texto.strip()) < 200:
            saida("  Atenção: quase não há texto nesse PDF. Se for um currículo escaneado, exporte de novo do Word/Canva.")
        break

    saida("\n— Inteligência artificial (recomendado) —")
    saida("  Com a chave da Anthropic, a nota de cada vaga vem de uma leitura de verdade dos requisitos,")
    saida("  e as respostas são escritas para cada vaga. Crie em console.anthropic.com (custa centavos por busca).")
    chave_atual = cfg["ia"]["chave_api"]
    while True:
        rotulo = "Cole a chave (Enter mantém a atual)" if chave_atual else "Cole a chave (Enter pula esta etapa)"
        nova = senha(f"{rotulo}: ").strip()
        if not nova:
            break
        ok, msg = testar_ia(nova)
        saida(f"  {msg}")
        if ok:
            cfg["ia"]["chave_api"] = nova
            break
    if cfg["ia"]["chave_api"]:
        import os
        os.environ.setdefault("ANTHROPIC_API_KEY", cfg["ia"]["chave_api"])

    sugestao = {}
    if cv_texto and ia.disponivel() and (not ca["resumo"] or not b["palavras_chave"]):
        if a.sim("Quer que a IA sugira um resumo profissional e os cargos para buscar, a partir do currículo?"):
            try:
                sugestao = (sugerir or sugerir_perfil)(cv_texto)
            except Exception as e:  # noqa: BLE001
                saida(f"  Não consegui gerar a sugestão agora ({e}). Seguimos sem ela.")

    saida("\n— O que procurar —")
    if sugestao.get("cargos") and not b["palavras_chave"]:
        saida(f"  Sugestão da IA: {', '.join(sugestao['cargos'])}")
        b["palavras_chave"] = sugestao["cargos"]
    b["palavras_chave"] = _lista(a.perguntar("Cargos que você procura, separados por vírgula", b["palavras_chave"]))
    b["cidades"] = _lista(a.perguntar("Cidades, separadas por vírgula (Enter vazio = qualquer lugar)", b["cidades"]))
    b["aceitar_remoto"] = a.sim("Aceita vagas remotas?", b["aceitar_remoto"])
    b["palavras_excluidas"] = _lista(a.perguntar("Termos para ignorar no título (ex.: sênior, estágio)", b["palavras_excluidas"]))

    if sugestao.get("resumo") and not ca["resumo"]:
        saida(f"\n  Resumo sugerido pela IA:\n  {sugestao['resumo']}\n")
        if a.sim("Usar este resumo? (você pode editar depois)"):
            ca["resumo"] = sugestao["resumo"]
    if not ca["resumo"]:
        ca["resumo"] = a.perguntar("Resumo profissional em 2 ou 3 frases (vai nas mensagens às empresas)", "")

    saida("\n— E-mail que envia candidaturas e o aviso diário (opcional) —")
    if a.sim("Configurar agora?", not cfg["smtp"]["usuario"]):
        sm = cfg["smtp"]
        sm["usuario"] = a.perguntar("E-mail que vai enviar (Gmail recomendado)", sm["usuario"] or ca["email"])
        auto = servidor_smtp(sm["usuario"])
        if auto:
            sm["servidor"], sm["porta"] = auto
            if "outlook" in auto[0]:
                saida("  Aviso: contas pessoais Hotmail/Outlook costumam bloquear esse acesso. Se falhar, use um Gmail.")
        else:
            sm["servidor"] = a.perguntar("Servidor SMTP", sm["servidor"])
            sm["porta"] = a.numero("Porta", int(sm["porta"]), 1, 65535)
        if "gmail" in sm["servidor"]:
            saida("  No Gmail, use uma senha de app: Conta Google → Segurança → Verificação em duas etapas → Senhas de app.")
        nova = senha("Senha (de app) do e-mail (Enter mantém a atual): ").strip()
        if nova:
            sm["senha"] = nova
        if sm["senha"] and a.sim("Testar o login agora?"):
            ok, msg = testar_email(sm)
            saida(f"  {msg}")

    salvar(cfg, caminho)
    saida(f"\nPronto! Configuração salva em {caminho}.")
    saida("Próximos passos: abra o painel (abrir_painel.bat ou python -m enviador painel) e clique em 'Buscar vagas agora'.")

    if sys.platform == "win32" and Path(caminho).with_name("agendar_tarefa.ps1").exists():
        if a.sim("Quer que a busca rode sozinha todo dia de manhã?"):
            try:
                subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                str(Path(caminho).with_name("agendar_tarefa.ps1"))], check=False)
            except Exception as e:  # noqa: BLE001
                saida(f"  Não consegui agendar ({e}). Rode depois: .\\agendar_tarefa.ps1")
    return cfg


def sugerir_perfil(cv: str) -> dict:
    from . import ia
    prompt = f"""A partir do currículo abaixo, sugira em português do Brasil:
- "resumo": um resumo profissional em primeira pessoa, 2 a 3 frases, só com fatos do currículo
  (nunca invente experiência, números ou ferramentas);
- "cargos": de 4 a 8 nomes de cargo, curtos, como aparecem em sites de vagas, compatíveis com o nível atual
  da pessoa (ex.: "analista de suporte", "técnico de TI").
Responda SOMENTE com JSON: {{"resumo": "...", "cargos": ["..."]}}

CURRÍCULO:
{cv[:8000]}"""
    d = ia.pedir_json(prompt, ia.MODELO_FORTE, 600)
    return {"resumo": str(d.get("resumo", "")).strip(),
            "cargos": [str(c).strip() for c in d.get("cargos", []) if str(c).strip()][:8]}
