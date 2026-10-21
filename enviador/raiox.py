"""Raio-x do mercado: o que as vagas da sua área pedem, o que você já tem e o que falta.

Duas fontes de informação:
1. Um catálogo de habilidades (abaixo), procurado no texto de cada vaga e no seu currículo.
   Funciona sempre, sem IA. Dá para acrescentar termos em `raiox.habilidades_extras` no config.
2. As lacunas apontadas pela IA em cada análise, quando a ANTHROPIC_API_KEY está configurada.
"""
from collections import Counter
from dataclasses import dataclass, field
import json
import re
import unicodedata

# nome exibido -> padrões (expressões regulares sobre texto minúsculo e sem acento)
CATALOGO: dict[str, list[str]] = {
    # Sistemas operacionais e servidores
    "Windows Server": [r"windows server"],
    "Windows 10/11": [r"windows 1[01]\b", r"\bwindows\b(?! server)"],
    "Linux": [r"\blinux\b", r"\bubuntu\b", r"\bcentos\b", r"\bdebian\b", r"red ?hat"],
    "macOS": [r"\bmac ?os\b"],
    "Active Directory": [r"active directory", r"\bad\b(?= ?/| e | ou |,)", r"\bgpo"],
    "Azure AD / Entra ID": [r"azure ad\b", r"entra id"],
    "Microsoft 365": [r"office ?365", r"microsoft ?365", r"\bm365\b", r"exchange online", r"sharepoint", r"\bteams\b"],
    "Exchange": [r"\bexchange\b"],
    "Intune / SCCM": [r"\bintune\b", r"\bsccm\b", r"\bmecm\b", r"endpoint manager"],
    "Virtualização (VMware/Hyper-V)": [r"vmware", r"vsphere", r"esxi", r"hyper-?v", r"proxmox", r"virtualiza"],
    "Backup (Veeam etc.)": [r"\bveeam\b", r"\bbackup"],
    # Nuvem
    "AWS": [r"\baws\b", r"amazon web services"],
    "Azure": [r"\bazure\b"],
    "Google Cloud": [r"google cloud", r"\bgcp\b"],
    # Redes e segurança
    "Redes TCP/IP": [r"tcp/?ip", r"\bredes\b", r"\bdns\b", r"\bdhcp\b", r"roteador"],
    "Cisco": [r"\bcisco\b"],
    "Certificação CCNA": [r"\bccna\b"],
    "MikroTik": [r"mikrotik"],
    "Firewall": [r"firewall", r"fortinet", r"fortigate", r"pfsense", r"palo alto", r"sophos"],
    "VPN": [r"\bvpn\b"],
    "Switches / VLAN": [r"\bswitch", r"\bvlan"],
    "Wi-Fi": [r"wi-?fi", r"wireless", r"access point"],
    "Segurança da informação": [r"seguranca da informacao", r"ciberseguranca", r"\bsiem\b", r"antivirus", r"\bedr\b"],
    "Cabeamento estruturado": [r"cabeamento", r"crimpagem", r"patch panel"],
    "Fibra óptica / FTTH": [r"\bftth\b", r"fibra optica", r"\bgpon\b", r"\bolt\b", r"\bonu\b"],
    "VoIP / PABX": [r"\bvoip\b", r"\bpabx\b", r"asterisk", r"telefonia"],
    # Monitoramento e observabilidade
    "Zabbix": [r"zabbix"],
    "Grafana": [r"grafana"],
    "Datadog": [r"datadog"],
    "Nagios / PRTG": [r"nagios", r"\bprtg\b"],
    # ITSM
    "ITIL": [r"\bitil\b"],
    "GLPI": [r"\bglpi\b"],
    "ServiceNow": [r"servicenow"],
    "Jira": [r"\bjira\b"],
    "Gestão de chamados": [r"chamados", r"tickets?\b", r"service ?desk", r"help ?desk"],
    "SLA / indicadores": [r"\bsla\b", r"indicadores", r"\bkpi"],
    # Suporte
    "Hardware / manutenção": [r"hardware", r"manutencao (?:preventiva|corretiva)", r"montagem de (?:micro|computador)"],
    "Impressoras": [r"impressora"],
    "Acesso remoto": [r"anydesk", r"teamviewer", r"acesso remoto", r"suporte remoto"],
    "PDV / TEF": [r"\bpdv\b", r"\btef\b", r"ponto de venda"],
    "Inventário de ativos": [r"inventario", r"gestao de ativos"],
    # Dados e programação
    "SQL": [r"\bsql\b"],
    "Oracle": [r"\boracle\b"],
    "PostgreSQL / MySQL": [r"postgres", r"mysql"],
    "SQL Server": [r"sql server"],
    "PowerShell": [r"powershell"],
    "Shell Script / Bash": [r"shell ?script", r"\bbash\b"],
    "Python": [r"\bpython\b"],
    "Docker / containers": [r"\bdocker\b", r"container", r"kubernetes", r"\bk8s\b"],
    "Git": [r"\bgit\b", r"github", r"gitlab"],
    "Power BI": [r"power ?bi"],
    "Excel avançado": [r"excel avancado", r"excel intermediario", r"\bexcel\b"],
    "ERP (SAP/TOTVS)": [r"\bsap\b", r"\btotvs\b", r"protheus", r"\berp\b"],
    # Requisitos gerais
    "Ensino superior (cursando/completo)": [r"superior (?:completo|cursando|em andamento)", r"graduacao", r"tecnologo", r"bacharel"],
    "Curso técnico": [r"curso tecnico", r"tecnico em informatica"],
    "Inglês": [r"\bingles\b", r"\benglish\b"],
    "Espanhol": [r"espanhol"],
    "CNH / disponibilidade para viagens": [r"\bcnh\b", r"disponibilidade para viag", r"veiculo proprio"],
    "Plantão / escala": [r"plantao", r"plantoes", r"escala 12x36", r"\b12x36\b", r"sobreaviso", r"24x7"],
}


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = t.encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t)          # junta termos quebrados em duas linhas no PDF


def _compilar(extras: dict | None = None) -> dict[str, re.Pattern]:
    cat = dict(CATALOGO)
    for nome, padroes in (extras or {}).items():
        cat[nome] = [p if isinstance(p, str) else str(p) for p in (padroes or [normalizar(nome)])]
    return {nome: re.compile("|".join(f"(?:{p})" for p in pads)) for nome, pads in cat.items()}


def habilidades_no_texto(texto: str, padroes: dict[str, re.Pattern]) -> set[str]:
    t = normalizar(texto)
    return {nome for nome, rx in padroes.items() if rx.search(t)}


@dataclass
class ItemRaiox:
    habilidade: str
    vagas: int              # em quantas vagas da área aparece
    percentual: int         # % das vagas da área
    tenho: bool             # aparece no seu currículo?
    em_quase: int = 0       # quantas vezes aparece nas vagas que você "quase" pegou


@dataclass
class Raiox:
    total_area: int
    total_quase: int
    faltam: list[ItemRaiox] = field(default_factory=list)
    tenho: list[ItemRaiox] = field(default_factory=list)
    lacunas_ia: list[tuple[str, int]] = field(default_factory=list)   # (lacuna, vezes)
    usou_ia: bool = False


def calcular(vagas, cv: str, config: dict | None = None) -> Raiox:
    """`vagas`: linhas do banco já analisadas (com nota, descricao, titulo, lacunas, metodo)."""
    cfg = (config or {}).get("raiox", {})
    nota_area = cfg.get("nota_minima_area", 30)          # abaixo disso a vaga é de outra área
    nota_min = (config or {}).get("analise", {}).get("nota_minima", 65)
    padroes = _compilar(cfg.get("habilidades_extras"))

    area = [v for v in vagas if (v["nota"] or 0) >= nota_area]
    quase = [v for v in area if (v["nota"] or 0) < nota_min + 15]   # perto da linha de corte
    no_cv = habilidades_no_texto(cv, padroes)

    contagem, contagem_quase = Counter(), Counter()
    for v in area:
        achadas = habilidades_no_texto(f"{v['titulo']} {v['descricao'] or ''}", padroes)
        contagem.update(achadas)
        if v in quase:
            contagem_quase.update(achadas)

    itens = [ItemRaiox(h, n, round(100 * n / len(area)), h in no_cv, contagem_quase[h])
             for h, n in contagem.most_common()] if area else []

    lacunas, usou_ia = Counter(), False
    for v in area:
        if v["metodo"] == "ia":
            usou_ia = True
        try:
            for l in json.loads(v["lacunas"] or "[]"):
                if l and len(l) <= 60:
                    lacunas[l.strip().rstrip(".")] += 1
        except (json.JSONDecodeError, TypeError):
            pass

    return Raiox(total_area=len(area), total_quase=len(quase),
                 faltam=[i for i in itens if not i.tenho],
                 tenho=[i for i in itens if i.tenho],
                 lacunas_ia=lacunas.most_common(15), usou_ia=usou_ia)


def imprimir(r: Raiox, saida=print, top: int = 12):
    if not r.total_area:
        saida("Ainda não há vagas analisadas da sua área. Rode `python -m enviador buscar` primeiro.")
        return
    saida(f"RAIO-X DO MERCADO — {r.total_area} vagas da sua área analisadas "
          f"({r.total_quase} perto da linha de corte)\n")
    saida("O QUE AS VAGAS PEDEM E VOCÊ AINDA NÃO MOSTRA NO CURRÍCULO")
    if not r.faltam:
        saida("  Nada relevante: seu currículo cobre o que aparece nas vagas.")
    for i in r.faltam[:top]:
        barra = "█" * max(1, i.percentual // 5)
        saida(f"  {i.percentual:>3}%  {barra:<20} {i.habilidade}")
    saida("\nO QUE VOCÊ JÁ TEM E É MAIS PEDIDO (destaque no currículo e nas entrevistas)")
    for i in r.tenho[:top]:
        saida(f"  {i.percentual:>3}%  {i.habilidade}")
    if r.lacunas_ia:
        saida("\nLACUNAS MAIS APONTADAS PELA ANÁLISE COM IA")
        for lac, n in r.lacunas_ia[:10]:
            saida(f"  {n:>3}x  {lac}")
    elif not r.usou_ia:
        saida("\nDica: com a ANTHROPIC_API_KEY configurada, o raio-x também mostra as lacunas que a IA "
              "aponta em cada vaga (requisitos de experiência, formação, nível de inglês etc.).")
    saida("\nAs porcentagens contam em quantas vagas da sua área o termo aparece. "
          "Elas indicam tendência, não requisito obrigatório.")
