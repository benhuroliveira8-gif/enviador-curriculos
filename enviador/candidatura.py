"""Candidatura semiautomática: o programa prepara tudo, você revisa e dá o clique final no site.

Para cada vaga recomendada (da maior nota para a menor):
  1. mostra a análise de compatibilidade;
  2. prepara respostas para as perguntas mais comuns dos formulários;
  3. salva tudo num arquivo e copia a mensagem principal para a área de transferência;
  4. abre a vaga no navegador;
  5. pergunta o que você fez: candidatei / depois / descartar / sair.
"""
from dataclasses import dataclass
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import webbrowser
from pathlib import Path

from .mensagem import MODELO_IA, limpar_cargo
from .modelos import Vaga

log = logging.getLogger(__name__)
PASTA = Path("candidaturas")


@dataclass
class Respostas:
    apresentacao: str        # "Fale sobre você" / carta de apresentação
    por_que_vaga: str        # "Por que você quer trabalhar aqui / nesta vaga?"
    destaques: list[str]     # experiências para mencionar se houver campo livre
    atencao: list[str]       # requisitos que você não tem: prepare-se para falar deles


def vaga_do_banco(linha) -> Vaga:
    return Vaga(fonte=linha["fonte"], id_externo=linha["chave"].split(":")[-1],
                titulo=linha["titulo"] or "", empresa=linha["empresa"] or "",
                descricao=linha["descricao"] or "", url=linha["url"] or "",
                cidade=linha["cidade"] or "", remoto=bool(linha["remoto"]))


# ---------- preparação das respostas ----------
def preparar(vaga: Vaga, analise_txt: str, cv: str, config: dict) -> Respostas:
    if config.get("mensagem", {}).get("usar_ia") and os.getenv("ANTHROPIC_API_KEY"):
        try:
            return _preparar_com_ia(vaga, analise_txt, cv, config["candidato"])
        except Exception as e:
            log.warning("IA indisponível, usando modelo: %s", e)
    return _preparar_modelo(vaga, analise_txt, config["candidato"])


def _extrair_lista(analise_txt: str, rotulo: str) -> list[str]:
    m = re.search(rf"{rotulo}: (.*?)(?: \| |$)", analise_txt or "")
    return [x.strip() for x in m.group(1).split(";")] if m else []


def _preparar_modelo(vaga: Vaga, analise_txt: str, candidato: dict) -> Respostas:
    cargo = limpar_cargo(vaga.titulo, vaga.empresa)
    empresa = f"a equipe da empresa {vaga.empresa}" if vaga.empresa else "a equipe"
    resumo = (candidato.get("resumo") or "").strip()
    primeira_frase = re.split(r"(?<=\.)\s", resumo, maxsplit=1)[0].rstrip(".")
    trajetoria = primeira_frase[0].lower() + primeira_frase[1:] if primeira_frase else "minha experiência"
    return Respostas(
        apresentacao=resumo,
        por_que_vaga=(f"A vaga de {cargo} combina diretamente com a minha trajetória: {trajetoria}. "
                      f"Quero levar essa experiência para {empresa}, contribuindo com um atendimento "
                      f"ágil e de qualidade, e continuar me desenvolvendo na área."),
        destaques=_extrair_lista(analise_txt, "A favor"),
        atencao=_extrair_lista(analise_txt, "Lacunas"),
    )


def _preparar_com_ia(vaga: Vaga, analise_txt: str, cv: str, candidato: dict) -> Respostas:
    import anthropic
    prompt = f"""Prepare respostas para o formulário de candidatura desta vaga, em português do Brasil,
em primeira pessoa, tom profissional e natural (sem clichês exagerados). Use SOMENTE fatos do
currículo: nunca invente experiências, ferramentas, certificações ou números.

Responda SOMENTE com JSON:
{{"apresentacao": "até 100 palavras, para 'fale sobre você'",
  "por_que_vaga": "até 90 palavras, conectando a experiência do candidato aos requisitos da vaga",
  "destaques": ["3 a 5 experiências concretas do currículo mais relevantes para esta vaga"],
  "atencao": ["requisitos da vaga que o candidato não comprova, e como abordar com honestidade numa entrevista"]}}

CURRÍCULO:
{cv[:8000]}

ANÁLISE PRÉVIA: {analise_txt}

VAGA: {vaga.titulo} | Empresa: {vaga.empresa or 'não informada'}
{vaga.descricao[:6000]}"""
    resp = anthropic.Anthropic().messages.create(
        model=MODELO_IA, max_tokens=1200, messages=[{"role": "user", "content": prompt}])
    texto = resp.content[0].text
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    d = json.loads(m.group(0) if m else texto)
    return Respostas(apresentacao=d.get("apresentacao", ""), por_que_vaga=d.get("por_que_vaga", ""),
                     destaques=list(d.get("destaques", [])), atencao=list(d.get("atencao", [])))


def respostas_para(banco, linha, cv: str, config: dict) -> Respostas:
    """Usa as respostas já guardadas para a vaga; se não houver, prepara e guarda."""
    if linha["respostas"]:
        try:
            return Respostas(**json.loads(linha["respostas"]))
        except (TypeError, ValueError):
            pass
    r = preparar(vaga_do_banco(linha), linha["analise"] or "", cv, config)
    banco.salvar_respostas(linha["chave"], r.__dict__)
    return r


# ---------- saída ----------
def texto_ficha(vaga: Vaga, nota, analise_txt: str, r: Respostas, candidato: dict) -> str:
    linhas = [
        f"VAGA: {vaga.titulo}",
        f"EMPRESA: {vaga.empresa or '?'}",
        f"NOTA: {nota}   |   {analise_txt}",
        f"LINK: {vaga.url}",
        "",
        "=== FALE SOBRE VOCÊ / APRESENTAÇÃO ===",
        r.apresentacao,
        "",
        "=== POR QUE VOCÊ QUER ESTA VAGA? ===",
        r.por_que_vaga,
    ]
    if r.destaques:
        linhas += ["", "=== DESTAQUES PARA MENCIONAR ==="] + [f"- {d}" for d in r.destaques]
    if r.atencao:
        linhas += ["", "=== ATENÇÃO: REQUISITOS QUE VOCÊ NÃO COMPROVA ==="] + [f"- {a}" for a in r.atencao]
    pret = candidato.get("pretensao_salarial")
    linhas += ["", "=== DADOS RÁPIDOS ===",
               f"Nome: {candidato.get('nome', '')}",
               f"E-mail: {candidato.get('email', '')}",
               f"Telefone: {candidato.get('telefone', '')}"]
    if candidato.get("linkedin"):
        linhas.append(f"LinkedIn: {candidato['linkedin']}")
    if pret:
        linhas.append(f"Pretensão salarial: {pret}")
    return "\n".join(linhas) + "\n"


def nome_arquivo(vaga: Vaga) -> str:
    base = f"{vaga.empresa or 'empresa'} - {limpar_cargo(vaga.titulo, vaga.empresa)}"
    base = re.sub(r'[<>:"/\\|?*\n\r\t]+', " ", base)
    return re.sub(r"\s+", " ", base).strip()[:90] + ".txt"


def salvar_ficha(vaga: Vaga, texto: str, pasta: Path = PASTA) -> Path:
    pasta.mkdir(exist_ok=True)
    caminho = pasta / nome_arquivo(vaga)
    caminho.write_text(texto, encoding="utf-8")
    return caminho


def copiar(texto: str) -> bool:
    """Copia para a área de transferência (Windows, Mac ou Linux). Retorna False se não conseguir."""
    try:
        if sys.platform == "win32":
            # Arquivo UTF-8 temporário evita problemas com acentos no PowerShell
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as f:
                f.write(texto)
            try:
                subprocess.run(["powershell", "-NoProfile", "-Command",
                                f"Get-Content -Raw -Encoding UTF8 '{f.name}' | Set-Clipboard"],
                               check=True, capture_output=True, timeout=15)
            finally:
                os.unlink(f.name)
        elif sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=texto.encode("utf-8"), check=True, timeout=15)
        else:
            subprocess.run(["xclip", "-selection", "clipboard"], input=texto.encode("utf-8"),
                           check=True, timeout=15)
        return True
    except Exception as e:
        log.info("Não consegui copiar para a área de transferência: %s", e)
        return False


# ---------- fluxo interativo ----------
OPCOES = "[c] candidatei   [d] depois   [x] descartar   [r] reabrir link   [s] sair"


def executar(banco, cv: str, config: dict, entrada=input, abrir=webbrowser.open, limite: int | None = None):
    fila = banco.fila_candidaturas()
    if limite:
        fila = fila[:limite]
    if not fila:
        print("Nenhuma vaga na fila. Rode `python -m enviador buscar` para procurar novas.")
        return
    print(f"{len(fila)} vagas na fila, da mais compatível para a menos.\n"
          f"As fichas ficam na pasta '{PASTA}'. Revise tudo antes de enviar: a candidatura é sua.\n")

    feitas = 0
    for n, linha in enumerate(fila, 1):
        vaga = vaga_do_banco(linha)
        print("=" * 70)
        print(f"[{n}/{len(fila)}] NOTA {linha['nota']}  {vaga.titulo}  |  {vaga.empresa or '?'}")
        print(f"  {linha['analise'] or ''}")
        print("  Preparando respostas...")
        r = respostas_para(banco, linha, cv, config)
        ficha = texto_ficha(vaga, linha["nota"], linha["analise"] or "", r, config["candidato"])
        caminho = salvar_ficha(vaga, ficha)

        print(f"\n--- Apresentação ---\n{r.apresentacao}\n\n--- Por que esta vaga ---\n{r.por_que_vaga}")
        if r.atencao:
            print("\n--- Atenção ---\n" + "\n".join(f"- {a}" for a in r.atencao))
        copiado = copiar(r.por_que_vaga)
        print(f"\nFicha completa: {caminho}")
        if copiado:
            print("'Por que esta vaga' foi copiado: é só colar (Ctrl+V) no formulário.")
        if vaga.url:
            abrir(vaga.url)
            print("Vaga aberta no navegador.")

        while True:
            escolha = (entrada(f"\n{OPCOES}\n> ") or "").strip().lower()[:1]
            if escolha == "r" and vaga.url:
                abrir(vaga.url)
                continue
            if escolha in ("c", "d", "x", "s"):
                break
            print("Opção inválida.")
        if escolha == "s":
            break
        status = {"c": "candidatei", "d": "depois", "x": "descartada"}[escolha]
        banco.marcar(linha["chave"], status)
        feitas += escolha == "c"
        print(f"Marcada como: {status}")

    print(f"\nPronto. {feitas} candidatura(s) registrada(s) nesta sessão. "
          f"Acompanhe com `python -m enviador feitas` ou pelo painel.")
