"""Sugestões para melhorar o currículo, a partir do que as vagas da sua área pedem.

Regras (sempre disponíveis) + sugestões escritas pela IA (com a chave da Anthropic).
Nenhuma sugestão inventa experiência: o que você não tem continua sendo decisão sua.
"""
import re

from . import ia
from .raiox import Raiox, normalizar


def sugestoes_regras(cv: str, rx: Raiox, config: dict, vagas_area=()) -> list[dict]:
    """Lista de {"tipo", "titulo", "detalhe"}. `tipo`: incluir, destacar, ajustar, cargo."""
    s: list[dict] = []
    t = normalizar(cv)
    inicio = t[: max(1200, len(t) // 4)]

    if rx.total_area < 5:
        s.append({"tipo": "ajustar", "titulo": "Ainda poucas vagas analisadas",
                  "detalhe": f"As sugestões ficam melhores com mais dados: hoje são {rx.total_area} vagas da sua área. "
                             "Faça mais algumas buscas."})

    for i in [i for i in rx.faltam if i.percentual >= 25][:4]:
        s.append({"tipo": "incluir", "titulo": f"Se você tem experiência com {i.habilidade}, coloque no currículo",
                  "detalhe": f"Aparece em {i.percentual}% das vagas da sua área e não está no seu currículo. "
                             "Triagens automáticas procuram essas palavras. Se não tem, é um bom tema para estudar."})

    from .raiox import _compilar
    padroes = _compilar((config.get("raiox") or {}).get("habilidades_extras"))
    for i in [i for i in rx.tenho if i.percentual >= 40][:8]:
        rx_hab = padroes.get(i.habilidade)
        if rx_hab and not rx_hab.search(inicio):
            s.append({"tipo": "destacar", "titulo": f"Traga {i.habilidade} para o início",
                      "detalhe": f"Você tem, e {i.percentual}% das vagas pedem, mas só aparece no meio ou no fim do "
                                 "currículo. Cite no resumo ou numa lista de habilidades no topo: o recrutador lê os primeiros segundos."})
        if len([x for x in s if x["tipo"] == "destacar"]) >= 2:
            break

    cargos = (config.get("busca") or {}).get("palavras_chave") or []
    titulos = [normalizar(v["titulo"] or "") for v in vagas_area]
    contagem = sorted(((sum(1 for tt in titulos if normalizar(c) in tt), c) for c in cargos), reverse=True)
    for n, c in contagem[:2]:
        if n >= 2 and normalizar(c) not in t:
            s.append({"tipo": "cargo", "titulo": f"Use o nome de cargo \"{c}\"",
                      "detalhe": f"Está no título de {n} vagas que você recebeu, mas não aparece no seu currículo. "
                                 "Se descreve o que você faz, use-o no objetivo ou no resumo."})

    if not re.search(r"\d+\s?%|\d+\s*(?:mil|chamados|tickets|usuarios|lojas|clientes|filiais|pontos|equipamentos|"
                     r"servidores|pessoas|atendimentos)", t):
        s.append({"tipo": "ajustar", "titulo": "Mostre resultados com números",
                  "detalhe": "Seu currículo descreve tarefas, mas não traz números. Exemplos: quantos chamados por dia, "
                             "quantas lojas ou usuários atendia, tempo médio de resolução, redução de incidentes."})
    if not (config.get("candidato") or {}).get("linkedin") and "linkedin" not in t:
        s.append({"tipo": "ajustar", "titulo": "Inclua o link do seu LinkedIn",
                  "detalhe": "Muitos recrutadores conferem o LinkedIn antes de chamar. Coloque o link no cabeçalho."})
    palavras = len(t.split())
    if palavras > 1100:
        s.append({"tipo": "ajustar", "titulo": "Currículo longo",
                  "detalhe": f"São cerca de {palavras} palavras. Tente caber em 1 ou 2 páginas, cortando "
                             "experiências antigas que não têm relação com as vagas que você busca."})
    elif palavras < 150:
        s.append({"tipo": "ajustar", "titulo": "Pouco texto no PDF",
                  "detalhe": "Quase não consegui ler texto. Se o currículo for imagem ou escaneado, triagens "
                             "automáticas também não leem. Exporte de novo pelo Word, Google Docs ou Canva."})
    return s


def sugestoes_ia(cv: str, rx: Raiox, config: dict) -> dict:
    """{"resumo_sugerido", "ajustes": [{"secao","sugestao","exemplo"}], "palavras_chave": [...]}"""
    faltam = ", ".join(f"{i.habilidade} ({i.percentual}%)" for i in rx.faltam[:12]) or "nenhuma"
    tenho = ", ".join(f"{i.habilidade} ({i.percentual}%)" for i in rx.tenho[:12]) or "nenhuma"
    lacunas = ", ".join(f"{l} ({n}x)" for l, n in rx.lacunas_ia[:10]) or "nenhuma"
    cargos = ", ".join((config.get("busca") or {}).get("palavras_chave") or [])
    prompt = f"""Você é especialista em currículos e recrutamento no Brasil. Sugira melhorias concretas no currículo
abaixo para as vagas que a pessoa procura ({cargos}).

Dados de {rx.total_area} vagas da área:
- muito pedido e AUSENTE no currículo: {faltam}
- muito pedido e PRESENTE no currículo: {tenho}
- lacunas mais apontadas nas análises: {lacunas}

Regras: nunca invente experiência, ferramenta, número ou certificação. Para o que a pessoa pode não ter,
escreva "se você tiver...". Nos exemplos, use [colchetes] para dados que só a pessoa sabe.
Escreva em português do Brasil.

Responda SOMENTE com JSON:
{{"resumo_sugerido": "novo resumo/objetivo em 3 a 4 linhas, só com fatos do currículo, usando os termos que as vagas usam",
  "ajustes": [{{"secao": "parte do currículo", "sugestao": "o que mudar e por quê", "exemplo": "como ficaria (pode ter [colchetes])"}}],
  "palavras_chave": ["termos que as vagas usam e que a pessoa já domina, para incluir de forma natural"]}}
Traga de 4 a 7 ajustes, do mais importante para o menos.

CURRÍCULO:
{cv[:9000]}"""
    d = ia.pedir_json(prompt, ia.MODELO_FORTE, 2500)
    return {"resumo_sugerido": str(d.get("resumo_sugerido", "")).strip(),
            "ajustes": [{"secao": str(a.get("secao", "")), "sugestao": str(a.get("sugestao", "")),
                         "exemplo": str(a.get("exemplo", ""))} for a in d.get("ajustes", []) if isinstance(a, dict)],
            "palavras_chave": [str(x) for x in d.get("palavras_chave", [])][:15]}


def imprimir(regras: list[dict], saida=print):
    if not regras:
        saida("Nada a sugerir por enquanto: seu currículo cobre bem o que as vagas pedem.")
        return
    saida("SUGESTÕES PARA O SEU CURRÍCULO\n")
    for i, s in enumerate(regras, 1):
        saida(f"{i}. {s['titulo']}\n   {s['detalhe']}\n")
