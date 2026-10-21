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

# Catálogo por área: nome exibido -> padrões (expressões regulares sobre texto minúsculo e sem acento).
# A área "geral" vale para todas. Em `raiox.areas` no config dá para limitar, ex.: ["ti", "administrativo"].
AREAS: dict[str, dict[str, list[str]]] = {
    "ti": {
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
        "AWS": [r"\baws\b", r"amazon web services"],
        "Azure": [r"\bazure\b"],
        "Google Cloud": [r"google cloud", r"\bgcp\b"],
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
        "Zabbix": [r"zabbix"],
        "Grafana": [r"grafana"],
        "Datadog": [r"datadog"],
        "Nagios / PRTG": [r"nagios", r"\bprtg\b"],
        "ITIL": [r"\bitil\b"],
        "GLPI": [r"\bglpi\b"],
        "ServiceNow": [r"servicenow"],
        "Jira": [r"\bjira\b"],
        "Gestão de chamados": [r"chamados", r"tickets?\b", r"service ?desk", r"help ?desk"],
        "SLA / indicadores": [r"\bsla\b", r"indicadores", r"\bkpi"],
        "Hardware / manutenção": [r"hardware", r"manutencao (?:preventiva|corretiva) de (?:computador|equipamento|micro)",
                                  r"montagem de (?:micro|computador)", r"manutencao de (?:computador|micro|notebook)"],
        "Impressoras": [r"impressora"],
        "Acesso remoto": [r"anydesk", r"teamviewer", r"acesso remoto", r"suporte remoto"],
        "PDV / TEF": [r"\bpdv\b", r"\btef\b", r"ponto de venda"],
        "Inventário de ativos": [r"inventario de (?:ativos|equipamentos|ti)", r"gestao de ativos", r"controle e inventario de ativos"],
        "SQL": [r"\bsql\b"],
        "Oracle": [r"\boracle\b"],
        "PostgreSQL / MySQL": [r"postgres", r"mysql"],
        "SQL Server": [r"sql server"],
        "PowerShell": [r"powershell"],
        "Shell Script / Bash": [r"shell ?script", r"\bbash\b"],
        "Python": [r"\bpython\b"],
        "Docker / containers": [r"\bdocker\b", r"container", r"kubernetes", r"\bk8s\b"],
        "Git": [r"\bgit\b", r"github", r"gitlab"],
    },
    "administrativo": {
        "Contas a pagar / receber": [r"contas a (?:pagar|receber)"],
        "Faturamento": [r"faturamento"],
        "Conciliação bancária": [r"conciliacao bancaria", r"conciliacoes"],
        "Notas fiscais": [r"notas? fisca(?:l|is)", r"\bnf-?e\b"],
        "Fluxo de caixa": [r"fluxo de caixa"],
        "Departamento pessoal / folha": [r"departamento pessoal", r"folha de pagamento", r"\bdp\b"],
        "Rotinas fiscais / contábeis": [r"rotinas? (?:fiscais|contabeis)", r"lancamentos contabeis", r"\bsped\b"],
        "Compras / cotações": [r"\bcompras\b", r"cotac(?:ao|oes)", r"fornecedores"],
        "Arquivo e documentação": [r"arquivo de documentos", r"controle de documentos", r"organizacao de documentos"],
    },
    "comercial": {
        "Prospecção de clientes": [r"prospeccao", r"prospectar"],
        "CRM (Salesforce, RD, HubSpot)": [r"\bcrm\b(?! ativo)", r"salesforce", r"rd station", r"hubspot", r"pipedrive"],
        "Metas de vendas": [r"metas? de vendas?", r"bater metas", r"cumprimento de metas"],
        "Negociação": [r"negociac(?:ao|oes)"],
        "Vendas B2B": [r"\bb2b\b"],
        "Pós-venda": [r"pos-?venda"],
        "Televendas / inside sales": [r"televendas", r"inside sales"],
    },
    "atendimento": {
        "Atendimento ao cliente": [r"atendimento ao (?:cliente|publico)"],
        "SAC / call center": [r"\bsac\b", r"call ?center", r"central de atendimento", r"telemarketing"],
        "Atendimento por chat / WhatsApp": [r"whatsapp", r"atendimento (?:via|por) chat"],
        "Recepção": [r"recepcao", r"recepcionista"],
    },
    "logistica": {
        "Controle de estoque": [r"controle de estoque", r"gestao de estoque", r"\bestoque\b"],
        "WMS": [r"\bwms\b"],
        "Expedição / recebimento": [r"expedicao", r"recebimento de (?:mercadorias|materiais)"],
        "Empilhadeira (NR-11)": [r"empilhadeira", r"\bnr-?11\b"],
        "Roteirização / transporte": [r"roteirizacao", r"gestao de frota", r"transportadoras?"],
    },
    "saude": {
        "COREN ativo": [r"\bcoren\b"],
        "CRM ativo (médico)": [r"crm ativo"],
        "Técnico / auxiliar de enfermagem": [r"(?:tecnico|auxiliar) de enfermagem"],
        "Suporte de vida (BLS/ACLS)": [r"\bbls\b", r"\bacls\b"],
        "Atendimento hospitalar": [r"\buti\b", r"pronto[- ]atendimento", r"centro cirurgico"],
    },
    "rh": {
        "Recrutamento e seleção": [r"recrutamento e selecao", r"\br&s\b", r"recrutamento"],
        "Treinamento e desenvolvimento": [r"treinamento e desenvolvimento", r"\bt&d\b"],
        "Benefícios": [r"gestao de beneficios", r"administracao de beneficios"],
        "eSocial": [r"esocial"],
        "Onboarding": [r"onboarding", r"integracao de (?:novos )?colaboradores"],
    },
    "marketing": {
        "Redes sociais": [r"redes sociais", r"social media", r"instagram"],
        "Tráfego pago (Google/Meta Ads)": [r"google ads", r"meta ads", r"facebook ads", r"trafego pago"],
        "SEO": [r"\bseo\b"],
        "Google Analytics": [r"google analytics", r"\bga4\b"],
        "Canva / design": [r"\bcanva\b", r"photoshop", r"illustrator"],
        "Copywriting / redação": [r"copywriting", r"redacao publicitaria", r"producao de conteudo"],
    },
    "manutencao": {
        "NR-10 (eletricidade)": [r"\bnr-?10\b"],
        "NR-35 (altura)": [r"\bnr-?35\b"],
        "NR-12 (máquinas)": [r"\bnr-?12\b"],
        "Manutenção elétrica": [r"manutencao eletrica", r"instalacoes eletricas", r"eletricista"],
        "Manutenção mecânica": [r"manutencao mecanica", r"mecanica industrial"],
        "CLP / automação": [r"\bclp\b", r"automacao industrial"],
        "Desenho técnico / AutoCAD": [r"desenho tecnico", r"autocad"],
        "Solda": [r"\bsolda"],
    },
    "geral": {
        "Excel": [r"\bexcel\b"],
        "Pacote Office": [r"pacote office", r"\bword\b", r"powerpoint"],
        "Power BI": [r"power ?bi"],
        "ERP (SAP/TOTVS)": [r"\bsap\b", r"\btotvs\b", r"protheus", r"\berp\b"],
        "Ensino superior (cursando/completo)": [r"superior (?:completo|cursando|em andamento)", r"graduacao", r"tecnologo", r"bacharel"],
        "Curso técnico": [r"curso tecnico", r"tecnico em [a-z]+"],
        "Inglês": [r"\bingles\b", r"\benglish\b"],
        "Espanhol": [r"espanhol"],
        "CNH / disponibilidade para viagens": [r"\bcnh\b", r"disponibilidade para viag", r"veiculo proprio"],
        "Plantão / escala": [r"plantao", r"plantoes", r"escala 12x36", r"\b12x36\b", r"sobreaviso", r"24x7"],
    },
}

NOMES_AREAS = {"ti": "Tecnologia", "administrativo": "Administrativo e financeiro", "comercial": "Comercial e vendas",
               "atendimento": "Atendimento", "logistica": "Logística", "saude": "Saúde", "rh": "Recursos humanos",
               "marketing": "Marketing", "manutencao": "Manutenção e indústria", "geral": "Requisitos gerais"}

# todas as áreas juntas (compatibilidade com quem importava CATALOGO)
CATALOGO: dict[str, list[str]] = {nome: pads for area in AREAS.values() for nome, pads in area.items()}


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = t.encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t)          # junta termos quebrados em duas linhas no PDF


def _compilar(extras: dict | None = None, areas: list[str] | None = None) -> dict[str, re.Pattern]:
    if areas:
        escolhidas = set(areas) | {"geral"}
        cat = {nome: pads for a, itens in AREAS.items() if a in escolhidas for nome, pads in itens.items()}
    else:
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
    padroes = _compilar(cfg.get("habilidades_extras"), cfg.get("areas") or None)

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
