"""Aprender com os resultados: quais candidaturas avançaram e o que isso diz sobre a busca.

"Avançou" = chegou a teste, entrevista, proposta ou aprovação.
"Não avançou" = reprovado, sem resposta, ou parada como enviada/em análise há 21 dias ou mais.
As sugestões só aparecem com dados suficientes, para não tirar conclusão de dois ou três casos.
"""
from collections import defaultdict
from datetime import datetime

from .raiox import normalizar

AVANCO = {"teste", "entrevista", "proposta", "aprovado"}
SEM_AVANCO = {"reprovado", "sem_resposta"}
DIAS_SEM_RESPOSTA = 21
MINIMO = 8                    # candidaturas com resultado para começar a sugerir
NOMES_FONTES = {"gupy": "Gupy", "adzuna": "Adzuna", "github": "GitHub"}
FAIXAS = [("abaixo de 65", 0, 64), ("65 a 74", 65, 74), ("75 a 84", 75, 84), ("85 ou mais", 85, 100)]


def _dias(iso, hoje):
    try:
        return (hoje - datetime.fromisoformat(iso)).days
    except (TypeError, ValueError):
        return 0


def _grupo(itens):
    av = sum(1 for i in itens if i["resultado"] == "avancou")
    dec = sum(1 for i in itens if i["resultado"] != "pendente")
    return {"total": len(itens), "com_resultado": dec, "avancaram": av,
            "taxa": round(100 * av / dec) if dec else None}


def analisar(banco, config: dict, hoje: datetime | None = None) -> dict:
    hoje = hoje or datetime.now()
    itens = []
    for r in banco.candidaturas():
        etapas = {h["etapa"] for h in banco.historico_etapas(r["chave"])} | {r["etapa"]}
        if etapas & AVANCO:
            resultado = "avancou"
        elif r["etapa"] in SEM_AVANCO or (r["etapa"] in ("candidatei", "em_analise")
                                          and _dias(r["etapa_em"], hoje) >= DIAS_SEM_RESPOSTA):
            resultado = "nao_avancou"
        else:
            resultado = "pendente"
        fonte = (r["fonte"] or "").split(":")[0]
        fonte = "Adicionada por você" if fonte == "manual" else NOMES_FONTES.get(fonte, fonte.capitalize())
        itens.append({"titulo": r["titulo"] or "", "empresa": r["empresa"] or "", "nota": r["nota"] or 0,
                      "fonte": fonte, "remoto": bool(r["remoto"]), "resultado": resultado,
                      "metodo": r["metodo"] or "palavras"})

    geral = _grupo(itens)
    faixas = [{"faixa": nome, **_grupo([i for i in itens if lo <= i["nota"] <= hi])} for nome, lo, hi in FAIXAS]
    por_fonte = defaultdict(list)
    for i in itens:
        por_fonte[i["fonte"]].append(i)
    fontes = sorted(({"fonte": f, **_grupo(v)} for f, v in por_fonte.items()), key=lambda g: -g["total"])
    modalidade = [{"modalidade": "Remoto", **_grupo([i for i in itens if i["remoto"]])},
                  {"modalidade": "Presencial / híbrido", **_grupo([i for i in itens if not i["remoto"]])}]
    cargos = []
    for c in (config.get("busca") or {}).get("palavras_chave") or []:
        grupo = [i for i in itens if normalizar(c) in normalizar(i["titulo"])]
        if grupo:
            cargos.append({"cargo": c, **_grupo(grupo)})
    cargos.sort(key=lambda g: -g["total"])

    return {"geral": geral, "faixas": faixas, "fontes": fontes, "modalidade": modalidade, "cargos": cargos,
            "sugestoes": sugerir(geral, faixas, fontes, cargos, config), "minimo": MINIMO}


def sugerir(geral, faixas, fontes, cargos, config) -> list[str]:
    if geral["com_resultado"] < MINIMO:
        falta = MINIMO - geral["com_resultado"]
        return [f"Ainda são {geral['com_resultado']} candidaturas com resultado. Faltam {falta} para as primeiras "
                "conclusões. Continue atualizando as etapas (inclusive \"reprovado\" e \"sem resposta\")."]
    s = []
    nota_min = (config.get("analise") or {}).get("nota_minima", 65)
    f = {x["faixa"]: x for x in faixas}
    baixa, alta = f["65 a 74"], f["85 ou mais"]
    if baixa["com_resultado"] >= 4 and alta["com_resultado"] >= 3:
        if baixa["taxa"] == 0 and alta["taxa"]:
            s.append(f"Nenhuma das {baixa['com_resultado']} candidaturas com nota 65 a 74 avançou, contra "
                     f"{alta['taxa']}% nas de 85 ou mais. Subir a nota mínima para 75 economiza tempo para as vagas "
                     "com chance real.")
        elif baixa["taxa"] and alta["taxa"] and baixa["taxa"] >= alta["taxa"] * 0.8 and nota_min >= 65:
            s.append(f"As vagas com nota 65 a 74 avançam quase tanto quanto as melhores ({baixa['taxa']}% contra "
                     f"{alta['taxa']}%). Vale baixar a nota mínima para {max(50, nota_min - 5)} e ver mais vagas.")
    for g in fontes:
        if g["com_resultado"] >= 5 and g["taxa"] == 0:
            s.append(f"Nenhuma das {g['com_resultado']} candidaturas vindas de \"{g['fonte']}\" avançou. "
                     "Considere dar menos tempo a essa fonte.")
    bons = [c for c in cargos if c["com_resultado"] >= 3 and c["taxa"]]
    ruins = [c for c in cargos if c["com_resultado"] >= 4 and c["taxa"] == 0]
    if bons:
        melhor = max(bons, key=lambda c: c["taxa"])
        s.append(f"Vagas de \"{melhor['cargo']}\" são as que mais avançam ({melhor['taxa']}%). "
                 "Priorize esse cargo e use esse nome no currículo.")
    for c in ruins:
        s.append(f"Nenhuma vaga de \"{c['cargo']}\" avançou em {c['com_resultado']} tentativas. "
                 "Talvez o nível ou os requisitos estejam acima do seu momento; veja as lacunas no raio-x.")
    if geral["taxa"] is not None and geral["taxa"] < 10 and geral["com_resultado"] >= 12:
        s.append(f"Só {geral['taxa']}% das candidaturas avançam. Antes de mandar mais, vale revisar o currículo "
                 "com as sugestões da aba Raio-x.")
    return s or ["Seus resultados estão equilibrados entre as faixas de nota e as fontes. Siga como está."]


def imprimir(r: dict, saida=print):
    g = r["geral"]
    saida(f"RESULTADOS — {g['total']} candidaturas, {g['com_resultado']} com resultado, "
          f"{g['avancaram']} avançaram" + (f" ({g['taxa']}%)" if g["taxa"] is not None else ""))
    saida("\nPor nota de compatibilidade")
    for x in r["faixas"]:
        if x["total"]:
            taxa = f"{x['taxa']}%" if x["taxa"] is not None else "aguardando"
            saida(f"  {x['faixa']:<14} {x['total']:>3} {'candidatura ' if x['total'] == 1 else 'candidaturas'}   avanço: {taxa}")
    saida("\nPor fonte")
    for x in r["fontes"]:
        taxa = f"{x['taxa']}%" if x["taxa"] is not None else "aguardando"
        saida(f"  {x['fonte']:<22} {x['total']:>3}   avanço: {taxa}")
    saida("\nO que isso sugere")
    for s in r["sugestoes"]:
        saida(f"  - {s}")
