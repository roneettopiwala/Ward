"""Personas: the people of a neighbourhood, sampled from census data.

Code decides everything factual: which census area someone lives in, their
age, tenure, commute, occupation group, household size, home point and the
places they use. The LLM only writes the human part (name, job title,
backstory, values, quirks) around those facts. Personas are generated once
per neighbourhood, stored, and reused for every proposal there.
"""

import json
import logging
import random
import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from services import interests, llm, voices
from settings import get_settings

log = logging.getLogger(__name__)

# About 15 people: mostly residents, plus people who work or spend time here.
ROLE_MIX = {"resident": 11, "worker": 3, "visitor": 1}
# People from across the city who join for landmarks and city-scale sites.
CITYWIDE_COUNT = 10
CITYWIDE_SEED = 1_000_000
HOME_SEARCH_M = 800
EVERYDAY_SEARCH_M = 600
GENERATION_TIMEOUT_S = 300
# Workers and visitors come from census areas within this distance of the neighbourhood.
COMMUTE_REACH_M = 10_000
# Modelling assumptions where the census tables we load don't say.
RETIRED_SHARE_65_PLUS = 0.8
STUDENT_SHARE_18_24 = 0.5

AGE_RANGES = {"15-24": (18, 24), "25-44": (25, 44), "45-64": (45, 64), "65+": (65, 88)}
OCCUPATIONS = {
    "management": "management",
    "business_finance_admin": "business, finance or administration",
    "sciences": "natural and applied sciences (e.g. tech, engineering)",
    "health": "health care",
    "education_law_government": "education, law, social or government services",
    "arts_culture_sport": "art, culture, recreation or sport",
    "sales_service": "sales and service",
    "trades_transport": "trades, transport or equipment operation",
    "natural_resources": "natural resources or agriculture",
    "manufacturing_utilities": "manufacturing or utilities",
}
COMMUTE_MODES = {
    "car": "car",
    "transit": "transit",
    "walk": "walk",
    "bike": "bike",
    "other": "other",
}
LANGUAGES = {
    "english": "English",
    "french": "French",
    "non_official": "a non-official language",
    "multiple": "English and another language",
}
HOUSING = {
    "single_detached": "a detached house",
    "semi_detached": "a semi-detached house",
    "row_house": "a row house",
    "duplex": "a duplex",
    "apartment_under_5_storeys": "a low-rise apartment",
    "apartment_5_plus_storeys": "a high-rise apartment",
    "other": "another kind of home",
}
# OSM categories for places people use routinely, and where people work.
EVERYDAY = [
    "grocery", "supermarket", "cafe", "convenience", "pharmacy", "fitness_centre", "restaurant",
    "pub", "bar", "bakery", "library", "community_centre", "hairdresser", "dry_cleaning",
    "clinic", "dentist", "ice_cream", "food_court", "brewery",
]  # fmt: skip
FAMILY = ["school", "childcare", "playground"]
PETS = ["pet", "veterinary"]
FOOD_AND_DRINK = ["cafe", "restaurant", "pub", "bar", "ice_cream", "food_court", "brewery"]
# Where someone in each census occupation group plausibly works.
_OFFICE = ["company", "bank", "hotel", "convention_centre"]
WORKPLACES = {
    "management": _OFFICE + ["restaurant", "hotel", "grocery"],
    "business_finance_admin": _OFFICE,
    "sciences": _OFFICE,
    "health": ["clinic", "dentist", "pharmacy", "physiotherapist", "optometrist"],
    "education_law_government": ["school", "library", "childcare", "post_office", "fire_station"],
    "arts_culture_sport": ["theatre", "museum", "aquarium", "stadium", "arts_centre", "gallery",
                           "fitness_centre"],
    "sales_service": ["restaurant", "cafe", "fast_food", "convenience", "grocery", "pharmacy",
                      "pub", "bar", "clothes", "hairdresser", "beauty", "hotel"],
    "trades_transport": ["hotel", "stadium", "convention_centre", "company", "parking"],
}  # fmt: skip
ANY_WORKPLACE = sorted({k for kinds in WORKPLACES.values() for k in kinds})
LOCAL_BUSINESS = {
    "restaurant", "cafe", "fast_food", "convenience", "grocery", "pharmacy", "pub", "bar",
    "clothes", "hairdresser", "beauty", "bakery",
}  # fmt: skip
DESTINATIONS = [
    "attraction", "stadium", "theatre", "museum", "aquarium", "arts_centre", "events_venue",
    "gallery", "marina", "baseball",
]  # fmt: skip

# Every place a persona can use, whatever table it lives in.
PLACES_SQL = """
places AS (
    SELECT fid, name, category AS kind, geom FROM pois
    UNION ALL SELECT fid, name, 'park', ST_PointOnSurface(geom) FROM parks
    UNION ALL SELECT fid, name, mode || ' stop', geom FROM transit_stops
    UNION ALL SELECT fid, name, 'building', ST_PointOnSurface(geom) FROM buildings
)
"""


class Place(BaseModel):
    fid: str
    name: str
    kind: str
    relation: str
    lnglat: tuple[float, float]


class Persona(BaseModel):
    id: uuid.UUID
    neighbourhood_id: int
    dguid: str | None
    role: str
    name: str
    age: int
    tenure: str | None
    commute_mode: str | None
    occupation: str
    household: str
    values: list[str]
    traits: dict[str, Any]
    """Quirks, tagline, census basis, relevance tags and other profile details."""
    stubbornness: float
    backstory: str
    model: str
    home: tuple[float, float]
    places: list[Place]

    @property
    def tags(self) -> list[str]:
        return self.traits.get("tags", [])


# ---------------------------------------------------------------- sampling


@dataclass
class Candidate:
    fid: str
    name: str
    kind: str


@dataclass
class Sampled:
    """One persona's facts, all from data, before the LLM writes the story."""

    key: int
    role: str
    dguid: str
    home_neighbourhood: str
    age_bucket: str
    age: int
    tenure: str
    commute_mode: str | None
    occupation_group: str
    household_size: str
    language: str
    housing: str | None
    home: tuple[float, float]
    places: list[Candidate] = field(default_factory=list)
    workplace_kind: str | None = None
    interests: list[interests.Chosen] = field(default_factory=list)

    def brief(self) -> dict[str, Any]:
        """What the LLM is told about this person."""
        return {
            "key": self.key,
            "role": self.role,
            "age": self.age,
            "lives_in": self.home_neighbourhood,
            "home": HOUSING.get(self.housing or "", None),
            "tenure": self.tenure,
            "household_size": self.household_size,
            "occupation": (
                OCCUPATIONS.get(self.occupation_group, self.occupation_group)
                if self.occupation_group not in ("retired", "student")
                else self.occupation_group
            ),
            "commute": self.commute_mode,
            "language_at_home": LANGUAGES.get(self.language, self.language),
            "places": [{"fid": p.fid, "name": p.name, "kind": p.kind} for p in self.places],
            "interests": [i.label for i in self.interests],
        }

    def based_on(self) -> str:
        low, high = AGE_RANGES[self.age_bucket]
        ages = f"{low}+" if self.age_bucket == "65+" else f"{low}–{high}"
        return (
            f"2021 Census profile for {self.tenure} households, age {ages}, "
            f"{self.home_neighbourhood}"
        )


def _pick(rng: random.Random, dist: dict[str, float] | None, default: str) -> str:
    items = [(k, v) for k, v in (dist or {}).items() if v and v > 0]
    if not items:
        return default
    keys, weights = zip(*items, strict=True)
    return rng.choices(keys, weights=weights)[0]


def _person_household_size(rng: random.Random, dist: dict[str, float] | None) -> str:
    """Household size for a person, not a household: big households hold more people."""
    if not dist:
        return "2"
    weighted = {k: v * (5.5 if k == "5+" else int(k)) for k, v in dist.items()}
    return _pick(rng, weighted, "2")


async def _census_areas(conn: AsyncConnection, neighbourhood_id: int) -> list[Any]:
    """Census areas in the neighbourhood and within commuting distance of it."""
    return list(
        (
            await conn.execute(
                text(
                    """
                    WITH home AS (SELECT geom FROM neighbourhoods WHERE id = :nid)
                    SELECT c.dguid, c.neighbourhood_id, n.name AS neighbourhood, c.population,
                           c.pct_renters, c.age_dist, c.occupation_dist, c.language_dist,
                           c.housing_dist, c.commute_dist, c.household_dist
                    FROM census_areas c JOIN neighbourhoods n ON n.id = c.neighbourhood_id, home
                    WHERE c.population > 0 AND c.age_dist IS NOT NULL
                      AND ST_DWithin(c.geom::geography, home.geom::geography, :reach)
                    """
                ),
                {"nid": neighbourhood_id, "reach": COMMUTE_REACH_M},
            )
        ).all()
    )


async def _home_point(conn: AsyncConnection, dguid: str, seed: int) -> tuple[float, float]:
    """A random point in a random residential building of the census area.

    Falls back to anywhere in the area when no building there is residential.
    Random, so no persona maps to a real address or person.
    """
    row = (
        await conn.execute(
            text(
                """
                WITH area AS (SELECT geom FROM census_areas WHERE dguid = :dguid),
                home AS (
                    SELECT b.geom FROM buildings b, area
                    WHERE b.use IN ('residential', 'mixed')
                      AND ST_Intersects(ST_PointOnSurface(b.geom), area.geom)
                    ORDER BY md5(b.fid || :salt)
                    LIMIT 1
                )
                , spot AS (SELECT COALESCE((SELECT geom FROM home), (SELECT geom FROM area)) AS g)
                SELECT ST_X(p) AS lng, ST_Y(p) AS lat FROM (
                    -- A random point inside; tiny or thin shapes can yield none,
                    -- so fall back to a point on the surface.
                    SELECT COALESCE(
                        (SELECT (ST_Dump(ST_GeneratePoints(spot.g, 1, :seed))).geom LIMIT 1),
                        ST_PointOnSurface(spot.g)
                    ) AS p
                    FROM spot
                ) s
                """
            ),
            {"dguid": dguid, "seed": seed, "salt": str(seed)},
        )
    ).one()
    return (row.lng, row.lat)


async def _nearby(
    conn: AsyncConnection,
    point: tuple[float, float],
    radius_m: float,
    kinds: list[str] | None = None,
    sources: tuple[str, ...] = ("pois",),
    neighbourhood_id: int | None = None,
    limit: int = 12,
) -> list[Candidate]:
    """Named places near a point (or inside a neighbourhood), nearest first."""
    where = ["name IS NOT NULL", "split_part(fid, ':', 1) = ANY(:prefixes)"]
    if kinds is not None:
        where.append("kind = ANY(:kinds)")
    if neighbourhood_id is not None:
        where.append("ST_Intersects(geom, (SELECT geom FROM neighbourhoods WHERE id = :nid))")
    else:
        where.append("ST_DWithin(geom::geography, ST_MakePoint(:lng, :lat)::geography, :r)")
    prefixes = [{"pois": "poi", "parks": "park", "transit_stops": "transit"}[s] for s in sources]
    rows = (
        await conn.execute(
            text(
                f"""
                WITH {PLACES_SQL}
                SELECT fid, name, kind FROM places
                WHERE {" AND ".join(where)}
                ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)
                LIMIT :limit
                """
            ),
            {
                "lng": point[0],
                "lat": point[1],
                "r": radius_m,
                "kinds": kinds,
                "nid": neighbourhood_id,
                "prefixes": prefixes,
                "limit": limit,
            },
        )
    ).all()
    return [Candidate(r.fid, r.name, r.kind) for r in rows]


async def _places_for(
    conn: AsyncConnection, rng: random.Random, s: Sampled, neighbourhood_id: int
) -> None:
    """2 to 4 routine places, chosen from what's really near the person."""
    chosen: list[Candidate] = []

    def take(options: list[Candidate], n: int = 1, nearest: bool = False) -> None:
        options = [o for o in options if o.fid not in {c.fid for c in chosen}]
        if nearest:
            chosen.extend(options[:n])
        else:
            chosen.extend(rng.sample(options, min(n, len(options))))

    if s.role == "resident":
        base = s.home
    elif s.role == "worker":
        kinds = WORKPLACES.get(s.occupation_group, ANY_WORKPLACE)
        workplaces = await _nearby(
            conn, s.home, 0, kinds, neighbourhood_id=neighbourhood_id, limit=200
        ) or await _nearby(
            conn, s.home, 0, ANY_WORKPLACE, neighbourhood_id=neighbourhood_id, limit=200
        )
        if workplaces:
            work = rng.choice(workplaces)
            chosen.append(work)
            s.workplace_kind = work.kind
            base = await _place_point(conn, work.fid)
        else:
            base = s.home
    else:  # visitor: comes for the neighbourhood's destinations
        spots = await _nearby(
            conn, s.home, 0, DESTINATIONS, neighbourhood_id=neighbourhood_id, limit=50
        )
        spots += await _nearby(
            conn, s.home, 0, sources=("parks",), neighbourhood_id=neighbourhood_id, limit=20
        )
        take(spots, 2)
        base = await _place_point(conn, chosen[0].fid) if chosen else s.home

    if s.commute_mode == "transit":
        take(await _nearby(conn, base, HOME_SEARCH_M, sources=("transit_stops",)), nearest=True)
    if s.role == "resident":
        take(await _nearby(conn, base, HOME_SEARCH_M, sources=("parks",), limit=4))
        if s.household_size in ("3", "4", "5+") and s.age < 55:
            take(await _nearby(conn, base, HOME_SEARCH_M, FAMILY))
        if rng.random() < 0.15:
            take(await _nearby(conn, base, HOME_SEARCH_M, PETS))
    everyday = EVERYDAY if s.role == "resident" else FOOD_AND_DRINK
    take(await _nearby(conn, base, EVERYDAY_SEARCH_M, everyday, limit=20), rng.randint(1, 2))
    s.places = chosen[:4]


async def _place_point(conn: AsyncConnection, fid: str) -> tuple[float, float]:
    row = (
        await conn.execute(
            text(f"WITH {PLACES_SQL} SELECT ST_X(geom) x, ST_Y(geom) y FROM places WHERE fid = :f"),
            {"f": fid},
        )
    ).one()
    return (row.x, row.y)


async def _person(
    conn: AsyncConnection, rng: random.Random, role: str, area: Any, key: int, seed: int
) -> Sampled:
    """One person's facts from their census area's distributions."""
    bucket = _pick(rng, {k: v for k, v in area.age_dist.items() if k != "0-14"}, "25-44")
    low, high = AGE_RANGES[bucket]
    age = rng.randint(low, high)
    working = role == "worker"
    if not working and age >= 65 and rng.random() < RETIRED_SHARE_65_PLUS:
        occupation = "retired"
    elif not working and age <= 24 and rng.random() < STUDENT_SHARE_18_24:
        occupation = "student"
    else:
        occupation = _pick(rng, area.occupation_dist, "sales_service")
    commuting = occupation != "retired"
    home = await _home_point(conn, area.dguid, seed)
    return Sampled(
        key=key,
        role=role,
        dguid=area.dguid,
        home_neighbourhood=area.neighbourhood,
        age_bucket=bucket,
        age=age,
        tenure="renter" if rng.random() < (area.pct_renters or 0.5) else "owner",
        commute_mode=(
            COMMUTE_MODES[_pick(rng, area.commute_dist, "transit")] if commuting else None
        ),
        occupation_group=occupation,
        household_size=_person_household_size(rng, area.household_dist),
        language=_pick(rng, area.language_dist, "english"),
        housing=_pick(rng, area.housing_dist, "") or None,
        home=home,
        interests=await interests.choose(conn, f"sampled:{seed}", age, home),
    )


async def sample(conn: AsyncConnection, neighbourhood_id: int) -> list[Sampled]:
    """The facts for each persona, drawn from census distributions. Seeded per area."""
    rng = random.Random(neighbourhood_id)
    areas = await _census_areas(conn, neighbourhood_id)
    local = [a for a in areas if a.neighbourhood_id == neighbourhood_id]
    elsewhere = [a for a in areas if a.neighbourhood_id != neighbourhood_id] or local
    if not local:
        raise ValueError(f"no census data for neighbourhood {neighbourhood_id}")

    out: list[Sampled] = []
    for role, count in ROLE_MIX.items():
        pool = local if role == "resident" else elsewhere
        for _ in range(count):
            area = rng.choices(pool, weights=[a.population for a in pool])[0]
            key = len(out)
            s = await _person(conn, rng, role, area, key, neighbourhood_id * 100 + key)
            await _places_for(conn, rng, s, neighbourhood_id)
            out.append(s)
    return out


async def sample_citywide(conn: AsyncConnection) -> list[Sampled]:
    """People from anywhere in the city, weighted by population."""
    rng = random.Random("citywide")
    areas = (
        await conn.execute(
            text(
                """
                SELECT c.dguid, c.neighbourhood_id, n.name AS neighbourhood, c.population,
                       c.pct_renters, c.age_dist, c.occupation_dist, c.language_dist,
                       c.housing_dist, c.commute_dist, c.household_dist
                FROM census_areas c JOIN neighbourhoods n ON n.id = c.neighbourhood_id
                WHERE c.population > 0 AND c.age_dist IS NOT NULL
                ORDER BY c.dguid
                """
            )
        )
    ).all()
    out: list[Sampled] = []
    for key in range(CITYWIDE_COUNT):
        area = rng.choices(areas, weights=[a.population for a in areas])[0]
        s = await _person(conn, rng, "citywide", area, key, CITYWIDE_SEED + key)
        # Their everyday places are around home, like a resident's.
        s.role = "resident"
        await _places_for(conn, rng, s, area.neighbourhood_id)
        s.role = "citywide"
        out.append(s)
    return out


# ---------------------------------------------------------------- the story


class Story(BaseModel):
    key: int
    name: str = Field(min_length=3, max_length=60)
    occupation: str = Field(min_length=2, max_length=80)
    household: str = Field(min_length=3, max_length=80)
    tagline: str = Field(min_length=5, max_length=90)
    backstory: str = Field(min_length=20, max_length=600)
    values: list[str] = Field(min_length=2, max_length=4)
    quirks: list[str] = Field(min_length=2, max_length=3)
    openness: float = Field(ge=0, le=1)
    trust_in_government: float = Field(ge=0, le=1)
    stubbornness: float = Field(ge=0, le=1)
    has_children: bool
    has_dog: bool
    places: dict[str, str]
    """fid -> how they use it, e.g. "walks the dog at"."""


class Stories(BaseModel):
    personas: list[Story]


def _story_problems(result: Stories, sampled: list[Sampled]) -> list[str]:
    found: list[str] = []
    by_key = {s.key: s for s in sampled}
    keys = [p.key for p in result.personas]
    if sorted(keys) != sorted(by_key):
        found.append(f"write exactly one persona per key {sorted(by_key)}; got keys {keys}")
    names = [p.name.split()[0].lower() for p in result.personas]
    repeated = sorted({n for n in names if names.count(n) > 1})
    if repeated:
        found.append(f"first names must all differ; repeated: {repeated}")
    for p in result.personas:
        s = by_key.get(p.key)
        if s is None:
            continue
        expected = {c.fid for c in s.places}
        if set(p.places) != expected:
            found.append(f"persona {p.key}: places must have exactly the fids {sorted(expected)}")
    return found


def _tags(s: Sampled, story: Story) -> list[str]:
    """Which catalog `relevant_to` groups this persona belongs to."""
    tags = {s.role + "s"}
    tags.add("renters" if s.tenure == "renter" else "homeowners")
    if story.has_children:
        tags.add("families")
    if s.age >= 65:
        tags.add("seniors")
    if story.has_dog:
        tags.add("dog_owners")
    if s.commute_mode in ("transit", "car"):
        tags.add("commuters")
    if s.workplace_kind in LOCAL_BUSINESS:
        tags.add("local_business")
    return sorted(tags)


async def write_stories(sampled: list[Sampled]) -> list[Story]:
    result, _ = await llm.complete_json(
        system=llm.prompt("persona_generate"),
        user=json.dumps({"personas": [s.brief() for s in sampled]}, ensure_ascii=False, indent=1),
        schema=Stories,
        check=lambda r: _story_problems(r, sampled),
        model=get_settings().persona_model,
        timeout_s=GENERATION_TIMEOUT_S,
    )
    return sorted(result.personas, key=lambda p: p.key)


# ---------------------------------------------------------------- storage


async def ensure(engine: AsyncEngine, neighbourhood_id: int) -> tuple[list[Persona], bool]:
    """The neighbourhood's personas, generating them on first use. True if just made."""
    async with engine.begin() as conn:
        # One generator per neighbourhood, even with several analyses at once.
        await conn.execute(text("SELECT pg_advisory_xact_lock(4, :n)"), {"n": neighbourhood_id})
        existing = await load(conn, neighbourhood_id)
        if existing:
            await add_missing_voices(conn, existing)
            if await add_missing_interests(conn, existing):
                existing = await load(conn, neighbourhood_id)
            return existing, False
        log.info("generating personas for neighbourhood %d", neighbourhood_id)
        sampled = await sample(conn, neighbourhood_id)
        stories = await write_stories(sampled)
        model = get_settings().reaction_model
        for s, story in zip(sampled, stories, strict=True):
            await _insert(conn, neighbourhood_id, s, story, model)
        return await load(conn, neighbourhood_id), True


async def ensure_citywide(engine: AsyncEngine) -> list[Persona]:
    """The citywide personas, generating them on first use."""
    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(4, 0)"))
        existing = await load_citywide(conn)
        if existing:
            return existing
        log.info("generating citywide personas")
        sampled = await sample_citywide(conn)
        stories = await write_stories(sampled)
        model = get_settings().reaction_model
        homes = {
            r.dguid: r.neighbourhood_id
            for r in await conn.execute(
                text("SELECT dguid, neighbourhood_id FROM census_areas WHERE dguid = ANY(:d)"),
                {"d": [s.dguid for s in sampled]},
            )
        }
        for s, story in zip(sampled, stories, strict=True):
            await _insert(conn, homes[s.dguid], s, story, model)
        return await load_citywide(conn)


async def _insert(
    conn: AsyncConnection, neighbourhood_id: int, s: Sampled, story: Story, model: str
) -> None:
    persona_id = uuid.uuid4()
    traits: dict[str, Any] = {
        "tagline": story.tagline,
        "quirks": story.quirks,
        "openness": story.openness,
        "trust_in_government": story.trust_in_government,
        "has_children": story.has_children,
        "has_dog": story.has_dog,
        "language_at_home": LANGUAGES.get(s.language, s.language),
        "housing": HOUSING.get(s.housing or ""),
        "occupation_group": s.occupation_group,
        "household_size": s.household_size,
        "based_on": s.based_on(),
        "tags": _tags(s, story),
        "interests": [i.model_dump() for i in s.interests],
    }
    traits["voice"] = voices.assign(
        voices.situation(str(persona_id), s.age, s.role, story.stubbornness, traits)
    )
    await conn.execute(
        text(
            """
            INSERT INTO personas (id, dguid, neighbourhood_id, role, name, age, tenure,
                                  commute_mode, occupation, household, values_list, traits,
                                  stubbornness, backstory, model, home)
            VALUES (:id, :dguid, :nid, :role, :name, :age, :tenure, :commute, :occupation,
                    :household, :values, CAST(:traits AS jsonb), :stubbornness, :backstory,
                    :model, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))
            """
        ),
        {
            "id": persona_id,
            "dguid": s.dguid,
            "nid": neighbourhood_id,
            "role": s.role,
            "name": story.name,
            "age": s.age,
            "tenure": s.tenure,
            "commute": s.commute_mode,
            "occupation": story.occupation,
            "household": story.household,
            "values": story.values,
            "traits": json.dumps(traits),
            "stubbornness": story.stubbornness,
            "backstory": story.backstory,
            "model": model,
            "lng": s.home[0],
            "lat": s.home[1],
        },
    )
    for c in s.places:
        await conn.execute(
            text(
                "INSERT INTO persona_places (persona_id, place_fid, relation) VALUES (:p, :f, :r)"
            ),
            {"p": persona_id, "f": c.fid, "r": story.places[c.fid]},
        )
    await _insert_interest_places(conn, persona_id, s.interests)


async def _insert_interest_places(
    conn: AsyncConnection, persona_id: uuid.UUID, chosen: list[interests.Chosen]
) -> None:
    for i in chosen:
        # A place they already use routinely keeps its everyday relation.
        await conn.execute(
            text(
                "INSERT INTO persona_places (persona_id, place_fid, relation) "
                "VALUES (:p, :f, :r) ON CONFLICT DO NOTHING"
            ),
            {"p": persona_id, "f": i.fid, "r": i.relation},
        )


async def backfill_interests(conn: AsyncConnection) -> int:
    """Give every stored persona without interests theirs. Fast once all have them."""
    ids = (
        (await conn.execute(text("SELECT id FROM personas WHERE NOT traits ? 'interests'")))
        .scalars()
        .all()
    )
    if ids:
        await add_missing_interests(conn, await load_ids(conn, list(ids)))
    return len(ids)


async def add_missing_interests(conn: AsyncConnection, personas: list[Persona]) -> bool:
    """Give personas made before interests existed theirs, once. True if any changed.

    Interests are drawn in code, so this is the same draw a new persona gets
    (seeded by the persona's id); reload the personas afterwards for the places.
    """
    changed = False
    for p in personas:
        if "interests" in p.traits:
            continue
        chosen = await interests.choose(conn, str(p.id), p.age, p.home)
        p.traits["interests"] = [i.model_dump() for i in chosen]
        await conn.execute(
            text(
                "UPDATE personas SET traits = jsonb_set(traits, '{interests}', "
                "CAST(:v AS jsonb)) WHERE id = :id"
            ),
            {"v": json.dumps(p.traits["interests"]), "id": p.id},
        )
        await _insert_interest_places(conn, p.id, chosen)
        changed = True
    return changed


async def add_missing_voices(conn: AsyncConnection, personas: list[Persona]) -> None:
    """Give personas made before voices existed one, once, and store it."""
    for p in personas:
        if "voice" in p.traits:
            continue
        p.traits["voice"] = voices.assign(
            voices.situation(str(p.id), p.age, p.role, p.stubbornness, p.traits)
        )
        await conn.execute(
            text(
                "UPDATE personas SET traits = jsonb_set(traits, '{voice}', CAST(:v AS jsonb)) "
                "WHERE id = :id"
            ),
            {"v": json.dumps(p.traits["voice"]), "id": p.id},
        )


async def load(conn: AsyncConnection, neighbourhood_id: int) -> list[Persona]:
    """A neighbourhood's own personas (citywide personas living there aren't in it)."""
    return await _load(
        conn, "p.neighbourhood_id = :n AND p.role <> 'citywide'", {"n": neighbourhood_id}
    )


async def load_citywide(conn: AsyncConnection) -> list[Persona]:
    return await _load(conn, "p.role = 'citywide'", {})


async def places_on_site(
    conn: AsyncConnection, geometry: dict[str, Any], replaces: list[str]
) -> set[str]:
    """Fids of every place the proposal replaces or builds on."""
    rows = await conn.execute(
        text(
            f"""
            WITH {PLACES_SQL}
            SELECT fid FROM places
            WHERE fid = ANY(:replaces)
               OR ST_Intersects(geom, ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326))
            """
        ),
        {"g": json.dumps(geometry), "replaces": replaces},
    )
    return set(rows.scalars())


async def load_using(conn: AsyncConnection, fids: set[str]) -> list[Persona]:
    """Personas from anywhere who use any of these places.

    Fans of a venue live all over the city; this is how they hear about it.
    """
    if not fids:
        return []
    ids = (
        (
            await conn.execute(
                text("SELECT DISTINCT persona_id FROM persona_places WHERE place_fid = ANY(:f)"),
                {"f": list(fids)},
            )
        )
        .scalars()
        .all()
    )
    return await load_ids(conn, list(ids)) if ids else []


def uses_any(p: Persona, fids: set[str]) -> bool:
    return any(pl.fid in fids for pl in p.places)


async def load_ids(conn: AsyncConnection, ids: list[uuid.UUID]) -> list[Persona]:
    return await _load(conn, "p.id = ANY(:ids)", {"ids": ids})


async def _load(conn: AsyncConnection, where: str, params: dict[str, Any]) -> list[Persona]:
    rows = (
        await conn.execute(
            text(
                f"""
                WITH {PLACES_SQL}
                SELECT p.*, ST_X(p.home) AS lng, ST_Y(p.home) AS lat,
                       COALESCE(json_agg(json_build_object(
                           'fid', pp.place_fid, 'name', pl.name, 'kind', pl.kind,
                           'relation', pp.relation,
                           'lnglat', json_build_array(ST_X(pl.geom), ST_Y(pl.geom))
                       ) ORDER BY pp.place_fid) FILTER (WHERE pl.fid IS NOT NULL), '[]')
                           AS places
                FROM personas p
                LEFT JOIN persona_places pp ON pp.persona_id = p.id
                LEFT JOIN places pl ON pl.fid = pp.place_fid
                WHERE {where}
                GROUP BY p.id
                ORDER BY p.created_at, p.id
                """
            ),
            params,
        )
    ).all()
    return [
        Persona(
            id=r.id,
            neighbourhood_id=r.neighbourhood_id,
            dguid=r.dguid,
            role=r.role,
            name=r.name,
            age=r.age,
            tenure=r.tenure,
            commute_mode=r.commute_mode,
            occupation=r.occupation,
            household=r.household,
            values=r.values_list or [],
            traits=r.traits or {},
            stubbornness=r.stubbornness,
            backstory=r.backstory,
            model=r.model,
            home=(r.lng, r.lat),
            places=[_place(p) for p in r.places],
        )
        for r in rows
    ]


def _place(raw: dict[str, Any]) -> Place:
    place = Place.model_validate(raw)
    if place.kind.endswith(" stop"):
        # 'Union Station - Northbound Platform ...' -> 'Union Station'
        place.name = place.name.split(" - ")[0]
    return place


# Groups that follow from how a persona gets to work (census commute mode).
COMMUTE_GROUPS = {"bike": "cyclists", "transit": "transit_riders", "car": "drivers"}


def groups(p: Persona) -> set[str]:
    """The catalog `relevant_to` groups a persona belongs to."""
    out = set(p.tags)
    if p.commute_mode in COMMUTE_GROUPS:
        out.add(COMMUTE_GROUPS[p.commute_mode])
    return out


def select(
    personas: list[Persona],
    relevant_to: list[str],
    limit: int = 15,
    touched: set[str] | None = None,
) -> list[Persona]:
    """The personas who react, most relevant to this kind of proposal first; with
    `touched` (place fids), those who use one of those places come first."""
    wanted = set(relevant_to)
    fids = touched or set()
    ranked = sorted(personas, key=lambda p: (not uses_any(p, fids), -len(wanted & groups(p))))
    return ranked[:limit]
