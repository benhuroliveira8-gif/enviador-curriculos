"""Analisa se o candidato tem chances reais em cada vaga.

Duas etapas:
1. Pré-filtro rápido e gratuito (sobreposição de termos entre currículo e vaga).
2. Análise cuidadosa com IA nas vagas mais promissoras: lê requisitos obrigatórios,
   senioridade, localização e compara com o currículo, devolvendo nota e justificativa.
Sem ANTHROPIC_API_KEY, a nota do pré-filtro é usada sozinha.
"""
from dataclasses import dataclass, field
import json
import logging
import os
import re
import unicodedata

log = logging.getLogger(__name__)
MODELO_IA = "claude-sonnet-5-5"

_STOP = set("""a o e de da do das dos em no na nos nas para por com sem um uma uns umas que se ao aos
as os ou como mais muito ser ter sua seu suas seus voce nos eles elas the and of to in for with
on at is are be you we our vaga vagas empresa trabalho area experiencia conhecimento conhecimentos
requisitos desejavel diferencial atividades responsabilidades beneficios""".split())


@dataclass
class Analise:
    nota: int                         # 0 a 100
    recomendada: bool
    resumo: str = ""
    pontos_fortes: list[str] = field(default_factory=list)
    lacunas: list[str] = field(default_factory=list)
    metodo: str = "palavras"          # "palavras" ou "ia"


def ler_curriculo(caminho: str) -> str:
    from pypdf import PdfReader
    logging.getLogger("pypdf").setLevel(logging.ERROR)   # avisos inofensivos de PDF malformado
    return "\n".join((p.extract_text() or "") for p in PdfReader(caminho).pages)


def _termos(texto: str) -> set[str]:
    t = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    return {w for w in re.findall(r"[a-z][a-z0-9+#.]{2,}", t) if w not in _STOP}


_NIVEL = set("jr junior pleno senior sr pl trainee temporario efetivo remoto hibrido presencial "
             "vaga talentos banco pcd".split())


def nota_rapida(cv: str, vaga) -> int:
    """Pré-filtro por palavras: 60% pelo cargo, 40% pela descrição.

    O cargo pesa mais porque é o sinal mais confiável. Na descrição, só uma parte dos termos
    é técnica (o resto é apresentação da empresa e benefícios), então ~40% de cobertura já
    conta como nota máxima nessa parte.
    """
    termos_cv = _termos(cv)
    titulo = _termos(vaga.titulo) - _NIVEL
    desc = _termos(vaga.descricao)
    p_titulo = len(titulo & termos_cv) / len(titulo) if titulo else 0
    if not desc:
        return round(100 * p_titulo)
    p_desc = min(1.0, (len(desc & termos_cv) / len(desc)) * 2.5)
    return round(100 * (0.6 * p_titulo + 0.4 * p_desc))


def analisar_com_ia(cv: str, vaga, candidato: dict, modelo: str | None = None) -> Analise:
    import anthropic
    prompt = f"""Você é um recrutador experiente e honesto. Avalie se este candidato tem chances REAIS
de passar na triagem desta vaga. Seja rigoroso: requisitos obrigatórios não atendidos, senioridade
incompatível, formação exigida ausente ou localização impossível derrubam a nota. Diferenciais
ausentes pesam pouco. Não seja otimista sem motivo.

Responda SOMENTE com JSON neste formato:
{{"nota": 0-100, "resumo": "1 frase", "pontos_fortes": ["..."], "lacunas": ["..."]}}

Em "pontos_fortes" e "lacunas", use itens CURTOS e padronizados (1 a 4 palavras), com o nome usual
da habilidade ou requisito, por exemplo: "AWS", "Windows Server", "Inglês avançado",
"Ensino superior completo", "CNH B", "Certificação CCNA". Nada de frases longas.

Escala: 80+ = perfil forte; 60-79 = chances reais; 40-59 = improvável; <40 = não se candidatar.

CURRÍCULO DO CANDIDATO:
{cv[:8000]}

Informações extras: {candidato.get('resumo', '')}

VAGA: {vaga.titulo}
Empresa: {vaga.empresa or 'não informada'} | Local: {vaga.cidade or 'não informado'} | Remoto: {'sim' if vaga.remoto else 'não informado'}
Descrição:
{vaga.descricao[:6000]}"""
    resp = anthropic.Anthropic().messages.create(
        model=modelo or MODELO_IA, max_tokens=600, messages=[{"role": "user", "content": prompt}])
    return interpretar_resposta_ia(resp.content[0].text)


def interpretar_resposta_ia(texto: str) -> Analise:
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    dados = json.loads(m.group(0) if m else texto)
    nota = max(0, min(100, int(dados.get("nota", 0))))
    return Analise(nota=nota, recomendada=False, resumo=dados.get("resumo", ""),
                   pontos_fortes=list(dados.get("pontos_fortes", []))[:5],
                   lacunas=list(dados.get("lacunas", []))[:5], metodo="ia")


def analisar_vagas(vagas: list, cv: str, config: dict) -> list[tuple]:
    """Devolve [(vaga, Analise)] ordenado da mais compatível para a menos."""
    cfg = config.get("analise", {})
    minima = cfg.get("nota_minima", 65)
    pre_minima = cfg.get("nota_minima_pre_filtro", 25)
    max_ia = cfg.get("max_analises_ia", 30)
    usar_ia = cfg.get("usar_ia", True) and bool(os.getenv("ANTHROPIC_API_KEY"))
    if cfg.get("usar_ia", True) and not usar_ia:
        log.warning("ANTHROPIC_API_KEY não definida: usando só a análise por palavras (menos precisa).")

    pre = sorted(((v, nota_rapida(cv, v)) for v in vagas), key=lambda x: x[1], reverse=True)
    resultado = []
    for i, (v, nota) in enumerate(pre):
        a = Analise(nota=nota, recomendada=False,
                    resumo=f"{nota}% de compatibilidade por palavras-chave")
        if usar_ia and i < max_ia and nota >= pre_minima:
            try:
                a = analisar_com_ia(cv, v, config.get("candidato", {}))
            except Exception as e:
                log.warning("Falha na análise com IA de '%s': %s", v.titulo, e)
        a.recomendada = a.nota >= minima
        resultado.append((v, a))
    return sorted(resultado, key=lambda x: x[1].nota, reverse=True)
