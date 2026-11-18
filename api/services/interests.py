"""Persona interests: what people do for fun, drawn from real participation rates.

Rates and sources live in api/data/interests.yaml. Each persona draws every
interest independently (rate times an age factor where the data has one), keeps
the rarest few, and is tied to a real place for each: a named venue for fans,
the nearest matching place for everything else. The places go in with the
persona's other places, so the impact code sees when a proposal replaces one.

Draws are seeded, so a persona's interests never change between runs.
"""

import random
from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

DATA = Path(__file__).resolve().parent.parent / "data" / "interests.yaml"
MAX_INTERESTS = 3


class PlaceRule(BaseModel):
    fid: str | None = None
    kinds: list[str] = []


class Interest(BaseModel):
    id: str
    label: str
    relation: str
    rate: float
    age_factor: str | None = None
    approximate: bool = False
    source: str
    place: PlaceRule


class Catalog(BaseModel):
    age_factors: dict[str, dict[str, float | str]]
    interests: list[Interest]


class Chosen(BaseModel):
    """An interest a persona has, and the real place it ties them to."""

    id: str
    label: str
    relation: str
    fid: str


@cache
def catalog() -> Catalog:
    return Catalog.model_validate(yaml.safe_load(DATA.read_text()))


def _rate(i: Interest, age: int) -> float:
    if not i.age_factor:
        return i.rate
    factors = catalog().age_factors[i.age_factor]
    factor = factors["65_plus"] if age >= 65 else factors["under_65"]
    return min(1.0, i.rate * float(factor))


def draw(seed: str, age: int) -> list[Interest]:
    """This persona's interests: each drawn at its rate, rarest kept first."""
    rng = random.Random(f"interests:{seed}")
    had = [i for i in catalog().interests if rng.random() < _rate(i, age)]
    return sorted(had, key=lambda i: _rate(i, age))[:MAX_INTERESTS]


async def _place_for(conn: AsyncConnection, i: Interest, home: tuple[float, float]) -> str | None:
    if i.place.fid:
        found = await conn.scalar(text("SELECT fid FROM pois WHERE fid = :f"), {"f": i.place.fid})
        return found
    return await conn.scalar(
        text(
            "SELECT fid FROM pois WHERE category = ANY(:kinds) AND name IS NOT NULL "
            "ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:lng, :lat), 4326) LIMIT 1"
        ),
        {"kinds": i.place.kinds, "lng": home[0], "lat": home[1]},
    )


async def choose(
    conn: AsyncConnection, seed: str, age: int, home: tuple[float, float]
) -> list[Chosen]:
    """Interests with their places; an interest with no matching place is dropped."""
    out = []
    for i in draw(seed, age):
        if fid := await _place_for(conn, i, home):
            out.append(Chosen(id=i.id, label=i.label, relation=i.relation, fid=fid))
    return out
