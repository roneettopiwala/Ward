from sqlalchemy import Engine

from ..area import Area
from ..db import upsert


def ingest(eng: Engine, area: Area) -> int:
    return upsert(eng, area.neighbourhoods, "neighbourhoods", "id")
