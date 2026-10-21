"""Histórico local (SQLite): vagas encontradas, análises, decisões e etapas das candidaturas.

Status da vaga (decisão sobre se candidatar):
    nova        recomendada, aguardando você decidir
    depois      você adiou
    baixa       a análise deu nota abaixo da mínima
    descartada  você descartou
    candidatei  você se candidatou pelo site
    enviada     o programa enviou por e-mail

Etapa (o que aconteceu depois da candidatura): ver ETAPAS.
"""
import json
import sqlite3
from datetime import date, datetime, timedelta

ESQUEMA = """
CREATE TABLE IF NOT EXISTS vagas (
    chave TEXT PRIMARY KEY, fonte TEXT, titulo TEXT, empresa TEXT, url TEXT,
    emails TEXT, encontrada_em TEXT, status TEXT DEFAULT 'nova',
    nota INTEGER, analise TEXT
);
CREATE TABLE IF NOT EXISTS envios (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chave TEXT, email TEXT,
    enviado_em TEXT, sucesso INTEGER, erro TEXT
);
CREATE TABLE IF NOT EXISTS etapas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chave TEXT, etapa TEXT, data TEXT, obs TEXT
);
"""

# Colunas adicionadas depois da primeira versão (bancos antigos ganham elas automaticamente)
_COLUNAS_NOVAS = {
    "descricao": "TEXT", "cidade": "TEXT", "remoto": "INTEGER", "atualizada_em": "TEXT",
    "lacunas": "TEXT", "pontos_fortes": "TEXT", "metodo": "TEXT",
    "etapa": "TEXT", "etapa_em": "TEXT", "followup_em": "TEXT", "respostas": "TEXT",
    "preparo": "TEXT",
}

ETAPAS = {
    "candidatei": "Enviada",
    "em_analise": "Em análise",
    "teste": "Teste / avaliação",
    "entrevista": "Entrevista",
    "proposta": "Proposta",
    "aprovado": "Aprovado",
    "reprovado": "Reprovado",
    "sem_resposta": "Sem resposta",
    "desisti": "Desisti",
}
ETAPAS_ATIVAS = ("candidatei", "em_analise", "teste", "entrevista", "proposta")
STATUS_CANDIDATURA = ("candidatei", "enviada")


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Banco:
    def __init__(self, caminho: str = "historico.db"):
        self.con = sqlite3.connect(caminho, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(ESQUEMA)
        existentes = {r["name"] for r in self.con.execute("PRAGMA table_info(vagas)")}
        for nome, tipo in _COLUNAS_NOVAS.items():
            if nome not in existentes:
                self.con.execute(f"ALTER TABLE vagas ADD COLUMN {nome} {tipo}")
        # candidaturas feitas antes do acompanhamento existir entram como "candidatei"
        self.con.execute(
            "UPDATE vagas SET etapa='candidatei', etapa_em=COALESCE(atualizada_em, encontrada_em) "
            "WHERE status IN ('candidatei','enviada') AND etapa IS NULL")
        self.con.commit()

    # ---------- vagas ----------
    def registrar_vaga(self, v) -> bool:
        """Retorna True se a vaga é nova."""
        cur = self.con.execute(
            "INSERT OR IGNORE INTO vagas (chave, fonte, titulo, empresa, url, emails, encontrada_em, "
            "descricao, cidade, remoto) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (v.chave, v.fonte, v.titulo, v.empresa, v.url, ",".join(v.emails),
             agora(), v.descricao, v.cidade, int(v.remoto)))
        self.con.commit()
        return cur.rowcount == 1

    def salvar_analise(self, chave: str, nota: int, texto: str, recomendada: bool,
                       lacunas=None, pontos_fortes=None, metodo: str = "", status: str | None = None):
        """Grava a análise. Sem `status`, a vaga vira 'nova' (recomendada) ou 'baixa'.
        Numa reanálise, uma vaga que você adiou continua adiada se ainda for recomendada."""
        if status is None:
            atual = self.con.execute("SELECT status FROM vagas WHERE chave=?", (chave,)).fetchone()
            adiada = atual is not None and atual["status"] == "depois"
            status = ("depois" if adiada else "nova") if recomendada else "baixa"
        self.con.execute(
            "UPDATE vagas SET nota=?, analise=?, status=?, lacunas=?, pontos_fortes=?, metodo=?, "
            "respostas=NULL WHERE chave=?",
            (nota, texto, status,
             json.dumps(lacunas or [], ensure_ascii=False),
             json.dumps(pontos_fortes or [], ensure_ascii=False), metodo, chave))
        self.con.commit()

    def vaga(self, id_ou_chave):
        campo = "rowid" if str(id_ou_chave).isdigit() else "chave"
        return self.con.execute(f"SELECT rowid AS id, * FROM vagas WHERE {campo}=?",
                                (id_ou_chave,)).fetchone()

    def listar(self, status: tuple[str, ...] | None = None, nota_min: int = 0, texto: str = ""):
        sql = "SELECT rowid AS id, * FROM vagas WHERE COALESCE(nota,0) >= ?"
        args: list = [nota_min]
        if status:
            sql += f" AND status IN ({','.join('?' * len(status))})"
            args += list(status)
        if texto:
            sql += " AND (titulo LIKE ? OR empresa LIKE ? OR cidade LIKE ?)"
            args += [f"%{texto}%"] * 3
        sql += " ORDER BY status='depois', nota DESC, encontrada_em DESC"
        return self.con.execute(sql, args).fetchall()

    def vagas_analisadas(self):
        return self.con.execute(
            "SELECT rowid AS id, * FROM vagas WHERE nota IS NOT NULL").fetchall()

    def fila_candidaturas(self):
        """Recomendadas sem e-mail, ainda não decididas ('nova') ou adiadas ('depois')."""
        return self.con.execute(
            "SELECT rowid AS id, * FROM vagas WHERE emails='' AND status IN ('nova','depois') "
            "ORDER BY status='depois', nota DESC").fetchall()

    def pendentes_manuais(self):
        """Vagas recomendadas sem e-mail, das mais compatíveis para as menos."""
        return self.con.execute(
            "SELECT titulo, empresa, url, nota, analise FROM vagas "
            "WHERE emails='' AND status='nova' ORDER BY nota DESC").fetchall()

    def marcar(self, chave: str, status: str):
        self.con.execute("UPDATE vagas SET status=?, atualizada_em=? WHERE chave=?",
                         (status, agora(), chave))
        if status in STATUS_CANDIDATURA:
            self._etapa(chave, "candidatei", "")
        self.con.commit()

    def salvar_preparo(self, chave: str, preparo: dict | None):
        self.con.execute("UPDATE vagas SET preparo=? WHERE chave=?",
                         (json.dumps(preparo, ensure_ascii=False) if preparo else None, chave))
        self.con.commit()

    def salvar_respostas(self, chave: str, respostas: dict):
        self.con.execute("UPDATE vagas SET respostas=? WHERE chave=?",
                         (json.dumps(respostas, ensure_ascii=False), chave))
        self.con.commit()

    # ---------- e-mail ----------
    def ja_enviado_para(self, email: str) -> bool:
        r = self.con.execute("SELECT 1 FROM envios WHERE email=? AND sucesso=1", (email,)).fetchone()
        return r is not None

    def enviados_hoje(self) -> int:
        hoje = date.today().isoformat()
        return self.con.execute(
            "SELECT COUNT(*) FROM envios WHERE sucesso=1 AND enviado_em LIKE ?", (hoje + "%",)
        ).fetchone()[0]

    def registrar_envio(self, chave: str, email: str, sucesso: bool, erro: str = ""):
        self.con.execute(
            "INSERT INTO envios (chave, email, enviado_em, sucesso, erro) VALUES (?,?,?,?,?)",
            (chave, email, agora(), int(sucesso), erro))
        if sucesso:
            self.con.execute("UPDATE vagas SET status='enviada', atualizada_em=? WHERE chave=?",
                             (agora(), chave))
            self._etapa(chave, "candidatei", f"enviado por e-mail para {email}")
        self.con.commit()

    # ---------- acompanhamento ----------
    def _etapa(self, chave: str, etapa: str, obs: str):
        quando = agora()
        self.con.execute("INSERT INTO etapas (chave, etapa, data, obs) VALUES (?,?,?,?)",
                         (chave, etapa, quando, obs))
        self.con.execute("UPDATE vagas SET etapa=?, etapa_em=?, followup_em=NULL WHERE chave=?",
                         (etapa, quando, chave))

    def registrar_etapa(self, chave: str, etapa: str, obs: str = ""):
        if etapa not in ETAPAS:
            raise ValueError(f"Etapa desconhecida: {etapa}. Use uma de: {', '.join(ETAPAS)}")
        self._etapa(chave, etapa, obs)
        self.con.commit()

    def historico_etapas(self, chave: str):
        return self.con.execute("SELECT etapa, data, obs FROM etapas WHERE chave=? ORDER BY id",
                                (chave,)).fetchall()

    def candidaturas(self, so_ativas: bool = False):
        sql = ("SELECT rowid AS id, * FROM vagas WHERE status IN ('candidatei','enviada')")
        if so_ativas:
            sql += f" AND etapa IN ({','.join('?' * len(ETAPAS_ATIVAS))})"
        sql += " ORDER BY etapa_em DESC"
        return self.con.execute(sql, ETAPAS_ATIVAS if so_ativas else ()).fetchall()

    def followups(self, dias: int = 10, hoje: datetime | None = None):
        """Candidaturas ativas sem novidade há `dias` dias (e sem follow-up recente)."""
        limite = ((hoje or datetime.now()) - timedelta(days=dias)).isoformat(timespec="seconds")
        return [r for r in self.candidaturas(so_ativas=True)
                if (r["etapa_em"] or "") <= limite and (r["followup_em"] or "") <= limite]

    def marcar_followup(self, chave: str):
        self.con.execute("UPDATE vagas SET followup_em=? WHERE chave=?", (agora(), chave))
        self.con.execute("INSERT INTO etapas (chave, etapa, data, obs) VALUES (?,?,?,?)",
                         (chave, "followup", agora(), "follow-up feito"))
        self.con.commit()

    # ---------- estatísticas ----------
    def resumo(self):
        return [tuple(r) for r in self.con.execute(
            "SELECT status, COUNT(*) FROM vagas GROUP BY status")]

    def contagem_etapas(self) -> dict:
        return {r[0]: r[1] for r in self.con.execute(
            "SELECT etapa, COUNT(*) FROM vagas WHERE etapa IS NOT NULL GROUP BY etapa")}
