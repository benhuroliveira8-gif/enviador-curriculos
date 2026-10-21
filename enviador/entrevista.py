"""Preparação para entrevista: perguntas prováveis, como responder com fatos do seu currículo,
o que perguntar ao recrutador e o que pesquisar antes.

Com a chave da Anthropic, tudo é feito sob medida para a vaga. Sem ela, sai um roteiro sólido
montado a partir da análise (pontos a favor e lacunas) e das perguntas mais comuns.
"""
import json
import logging

from . import ia
from .mensagem import limpar_cargo

log = logging.getLogger(__name__)


def _lista(valor) -> list:
    try:
        return list(json.loads(valor or "[]"))
    except (TypeError, ValueError):
        return []


def preparo_do_banco(banco, linha, cv: str, config: dict, refazer: bool = False) -> dict:
    """Usa o preparo guardado; se não houver (ou `refazer`), gera e guarda."""
    if linha["preparo"] and not refazer:
        try:
            return json.loads(linha["preparo"])
        except (TypeError, ValueError):
            pass
    p = preparar(linha, cv, config)
    banco.salvar_preparo(linha["chave"], p)
    return p


def preparar(linha, cv: str, config: dict) -> dict:
    if ia.disponivel() and config.get("mensagem", {}).get("usar_ia", True):
        try:
            return _com_ia(linha, cv, config)
        except Exception as e:  # noqa: BLE001
            log.warning("Preparo com IA falhou, usando roteiro padrão: %s", e)
    return _roteiro(linha, config)


def _roteiro(linha, config: dict) -> dict:
    cargo = limpar_cargo(linha["titulo"] or "", linha["empresa"] or "")
    nome = linha["empresa"] or ""
    na = f"na empresa {nome}" if nome else "nesta empresa"
    da = f"da empresa {nome}" if nome else "da empresa"
    fortes = _lista(linha["pontos_fortes"])
    lacunas = _lista(linha["lacunas"])
    resumo = (config.get("candidato", {}).get("resumo") or "").strip()

    perguntas = [
        {"pergunta": "Fale um pouco sobre você.",
         "motivo": "Abre quase toda entrevista. Avaliam clareza e se sua trajetória conversa com a vaga.",
         "como_responder": "Em até 2 minutos: onde você está hoje, as experiências mais ligadas à vaga e por "
                           f"que quer este passo. Base: {resumo}" if resumo else
                           "Em até 2 minutos: onde você está hoje, as experiências mais ligadas à vaga e por que quer este passo."},
        {"pergunta": f"Por que você quer trabalhar como {cargo} {na}?",
         "motivo": "Mostra se você pesquisou a empresa e se o interesse é real.",
         "como_responder": "Ligue algo concreto da empresa (produto, clientes, momento) ao que você já faz bem. "
                           "Evite respostas que serviriam para qualquer empresa."},
        {"pergunta": "Conte uma situação difícil que você resolveu no trabalho.",
         "motivo": "Pergunta comportamental: querem ver como você age sob pressão.",
         "como_responder": "Use o método STAR: Situação (contexto), Tarefa (o que cabia a você), Ação (o que você "
                           "fez, passo a passo) e Resultado (o que mudou, com número se tiver). Escolha um caso real."},
    ]
    for f in fortes[:3]:
        perguntas.append({
            "pergunta": f"Como foi a sua experiência com {f}?",
            "motivo": "É um ponto forte seu para esta vaga; espere perguntas detalhadas.",
            "como_responder": f"Dê um exemplo concreto de quando usou {f}: o problema, o que você fez e o resultado. "
                              "Detalhes técnicos mostram que a experiência é de verdade."})
    for l in lacunas[:3]:
        perguntas.append({
            "pergunta": f"Você tem experiência com {l}?",
            "motivo": "A vaga pede isso e seu currículo não mostra. É provável que perguntem.",
            "como_responder": f"Seja honesto. Se já teve contato, conte em que nível. Se não, mostre algo parecido "
                              f"que você domina e como pretende aprender {l} (curso, laboratório em casa, documentação)."})
    perguntas += [
        {"pergunta": "Quais são seus pontos fortes e o que você ainda quer desenvolver?",
         "motivo": "Avaliam autoconhecimento.",
         "como_responder": "Um ponto forte com exemplo, e um ponto a desenvolver real, dizendo o que já está fazendo a respeito."},
        {"pergunta": "Qual a sua pretensão salarial?",
         "motivo": "Costuma aparecer já na primeira conversa com o RH.",
         "como_responder": "Pesquise a faixa do cargo na sua cidade (Glassdoor, Vagas, LinkedIn) e responda com "
                           "uma faixa, perguntando também sobre os benefícios."},
    ]
    return {
        "metodo": "roteiro",
        "perguntas": perguntas,
        "para_perguntar": [
            "Como é um dia típico nessa função?",
            "Quais são os maiores desafios da equipe hoje?",
            "Como vocês medem o sucesso de quem entra nessa vaga nos primeiros meses?",
            "Quais são os próximos passos do processo seletivo?",
        ],
        "pesquisar": [
            f"Site e redes sociais {da}: o que vende, para quem, notícias recentes.",
            f"Página {da} no LinkedIn e perfis de quem trabalha na área.",
            "Avaliações de funcionários (Glassdoor) e de clientes (Reclame Aqui).",
            "Releia a descrição da vaga e marque cada requisito com um exemplo seu.",
        ],
    }


def _com_ia(linha, cv: str, config: dict) -> dict:
    prompt = f"""Você é um recrutador experiente preparando um candidato para a entrevista desta vaga.
Escreva em português do Brasil. Use SOMENTE fatos do currículo nas sugestões de resposta; quando faltar
um dado (número, nome de sistema), escreva entre colchetes para o candidato completar, ex.: "[quantos chamados por dia]".

Responda SOMENTE com JSON:
{{"perguntas": [{{"pergunta": "...", "motivo": "por que provavelmente vão perguntar isso", "como_responder": "roteiro em 2 a 4 frases, citando experiências reais do currículo; use STAR nas comportamentais"}}],
  "para_perguntar": ["3 a 5 perguntas inteligentes para o candidato fazer ao recrutador"],
  "pesquisar": ["3 a 5 itens objetivos para pesquisar sobre a empresa e a área antes da entrevista"]}}

Inclua de 8 a 10 perguntas: as técnicas mais prováveis para os requisitos da vaga, as comportamentais
mais comuns, e as que tocam nas lacunas do candidato (com uma forma honesta de responder).

CURRÍCULO:
{cv[:8000]}

ANÁLISE DA VAGA: {linha["analise"] or ""}

VAGA: {linha["titulo"]} | Empresa: {linha["empresa"] or "não informada"}
{(linha["descricao"] or "")[:6000]}"""
    d = ia.pedir_json(prompt, ia.MODELO_FORTE, 2500)
    perguntas = [{"pergunta": str(p.get("pergunta", "")).strip(), "motivo": str(p.get("motivo", "")).strip(),
                  "como_responder": str(p.get("como_responder", "")).strip()}
                 for p in d.get("perguntas", []) if isinstance(p, dict) and p.get("pergunta")]
    if not perguntas:
        raise ia.ErroIA("A IA não devolveu perguntas.")
    return {"metodo": "ia", "perguntas": perguntas,
            "para_perguntar": [str(x) for x in d.get("para_perguntar", [])][:6],
            "pesquisar": [str(x) for x in d.get("pesquisar", [])][:6]}


def texto(linha, p: dict) -> str:
    """Versão em texto, para o terminal ou para salvar."""
    out = [f"PREPARAÇÃO PARA ENTREVISTA — {linha['titulo']} | {linha['empresa'] or '?'}", ""]
    for i, q in enumerate(p["perguntas"], 1):
        out += [f"{i}. {q['pergunta']}", f"   Por que perguntam: {q['motivo']}", f"   Como responder: {q['como_responder']}", ""]
    out += ["PERGUNTAS PARA VOCÊ FAZER"] + [f"- {x}" for x in p["para_perguntar"]] + [""]
    out += ["PESQUISE ANTES"] + [f"- {x}" for x in p["pesquisar"]]
    return "\n".join(out) + "\n"
