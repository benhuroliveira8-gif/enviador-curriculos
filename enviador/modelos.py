from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Vaga:
    fonte: str                      # "gupy", "github:backend-br/vagas", ...
    id_externo: str                 # id único dentro da fonte
    titulo: str
    empresa: str = ""
    descricao: str = ""
    url: str = ""
    cidade: str = ""
    remoto: bool = False
    publicada_em: Optional[datetime] = None
    emails: list[str] = field(default_factory=list)

    @property
    def chave(self) -> str:
        return f"{self.fonte}:{self.id_externo}"

    @property
    def aceita_email(self) -> bool:
        return bool(self.emails)
