"""Neighbourhood context cards: what a neighbourhood is like, from data only.

Four short sections: who lives there (census), recent development applications,
everyday places, and what residents raised at past consultations. Each persona's
reaction prompt gets their own neighbourhood's card; the results panel shows a
card for each neighbourhood a proposal affects.

Counts and shares only: no reputation labels or adjectives, no crime data, and
no language or other identity data (personas keep their own traits; the card
must not invite reasoning from who lives somewhere).
"""

import re
from datetime import date

from pydantic import BaseModel, computed_field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

DEVELOPMENTS_SINCE = date(2022, 1, 1)
RECENT_SHOWN = 3
SUMMARY_CHARS = 160
ANCHORS_SHOWN = 3
THEMES_SHOWN = 3
MIN_LOCAL_COMMENTS = 5
"""With fewer comments than this, themes come from comments within NEARBY_M."""
NEARBY_M = 3000
MIN_SHARE = 0.05
"""Home types and commute modes below this share are left out."""

HOMES = {
    "single_detached": "detached houses",
    "semi_detached": "semi-detached houses",
    "row_house": "row houses",
    "duplex": "duplexes",
    "apartment_under_5_storeys": "low-rise apartments",
    "apartment_5_plus_storeys": "high-rise apartments",
}
COMMUTES = {"car": "drive", "transit": "take transit", "walk": "walk", "bike": "cycle"}
# Labels are (singular, plural).
APPLICATION_TYPES = {
    "OZ": ("rezoning", "rezonings"),
    "SA": ("site plan", "site plans"),
    "SB": ("subdivision", "subdivisions"),
    "CD": ("condominium approval", "condominium approvals"),
    "PL": ("part-lot exemption", "part-lot exemptions"),
}
# Everyday places counted in each neighbourhood: (labels, OSM categories).
PLACE_COUNTS = [
    (("school", "schools"), ["school"]),
    (("grocery store", "grocery stores"), ["grocery", "supermarket"]),
    (("library", "libraries"), ["library"]),
    (("community centre", "community centres"), ["community_centre"]),
    (("clinic", "clinics"), ["clinic", "doctors"]),
    (("childcare centre", "childcare centres"), ["childcare"]),
]
PARKS = ("park", "parks")
TRANSIT = [
    ("subway", ("subway station", "subway stations")),
    ("lrt", ("LRT stop", "LRT stops")),
    ("streetcar", ("streetcar stop", "streetcar stops")),
    ("bus", ("bus stop", "bus stops")),
]
# Application statuses in plain words; others are just lower-cased.
STATUSES = {
    "omb appeal": "under appeal",
    "olt appeal": "under appeal",
    "appeal received": "under appeal",
    "omb approved": "approved on appeal",
    "olt approved": "approved on appeal",
    "noac issued": "site plan approved",
}
# City shorthand in application descriptions.
SHORTHAND = [
    (re.compile(r"\b\d{2} \d{6} [A-Z]{3} \d{2} [A-Z]{2}\b\s*"), ""),
    (re.compile(r"\bZBA\b"), "zoning amendment"),
    (re.compile(r"\bOPA\b"), "Official Plan amendment"),
]


class Development(BaseModel):
    address: str
    submitted: str
    """Year and month, e.g. "2026-05"."""
    status: str
    summary: str


class ContextCard(BaseModel):
    neighbourhood_id: int
    name: str
    people: list[str]
    developments_total: int
    developments_by_type: dict[str, int]
    recent_developments: list[Development]
    places: list[str]
    anchors: list[str]
    """Named places: the largest parks and rapid transit stations."""
    themes: list[str]
    """What residents most often raised, most common first, in plain words."""
    themes_comments: int
    themes_scope: str
    """"this neighbourhood", "within 3 km" or "" when there are no comments."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def developments_summary(self) -> str:
        """E.g. "23 applications since 2022: 10 rezonings, 10 site plans"."""
        if not self.developments_total:
            return f"No development applications since {DEVELOPMENTS_SINCE.year}"
        types = ", ".join(
            f"{n} {_plural(APPLICATION_TYPES.get(t, (t, t)), n)}"
            for t, n in self.developments_by_type.items()
        )
        noun = "application" if self.developments_total == 1 else "applications"
        return f"{self.developments_total} {noun} since {DEVELOPMENTS_SINCE.year}: {types}"

    def for_prompt(self) -> dict:
        """The compact version a persona sees."""
        recent = [
            f"{d.address} ({d.submitted[:4]}, {d.status}): {d.summary}"
            for d in self.recent_developments
        ]
        view: dict = {
            "name": self.name,
            "people": self.people,
            "development_applications": self.developments_summary,
            "recent_proposals": recent,
            "everyday_places": self.places + self.anchors,
        }
        if self.themes:
            view["what_residents_often_raise"] = (
                f"{', '.join(self.themes)} (from {self.themes_comments} comments, "
                f"{self.themes_scope})"
            )
        return view


def _plural(labels: tuple[str, str], n: int) -> str:
    return labels[0] if n == 1 else labels[1]


def _pct(share: float) -> str:
    return f"{round(share * 100)}%"


def _top(dist: dict[str, float], labels: dict[str, str], n: int) -> list[tuple[str, float]]:
    ranked = sorted(
        ((k, v) for k, v in dist.items() if k in labels and v >= MIN_SHARE), key=lambda kv: -kv[1]
    )
    return [(labels[k], v) for k, v in ranked[:n]]


def _summary(description: str | None) -> str:
    text_ = description or ""
    for pattern, plain in SHORTHAND:
        text_ = pattern.sub(plain, text_)
    text_ = " ".join(text_.split())
    first = text_.split(". ")[0].rstrip(".")
    if len(first) <= SUMMARY_CHARS:
        return first
    return first[:SUMMARY_CHARS].rsplit(" ", 1)[0] + "…"


def _theme_label(theme: str) -> str:
    return theme.replace("_and_", " and ").replace("_", " ")


async def _people(conn: AsyncConnection, nid: int) -> list[str]:
    totals = (
        await conn.execute(
            text(
                """
                SELECT sum(population) AS pop,
                       sum(median_age * population) / NULLIF(sum(population)
                         FILTER (WHERE median_age IS NOT NULL), 0) AS age,
                       sum(pct_renters * population) / NULLIF(sum(population)
                         FILTER (WHERE pct_renters IS NOT NULL), 0) AS renters
                FROM census_areas WHERE neighbourhood_id = :nid
                """
            ),
            {"nid": nid},
        )
    ).one()
    if not totals.pop:
        return []

    async def dist(column: str) -> dict[str, float]:
        rows = await conn.execute(
            text(
                f"""
                SELECT d.key, sum(d.value::float * c.population) / NULLIF(sum(c.population), 0)
                FROM census_areas c, jsonb_each_text(c.{column}) d
                WHERE c.neighbourhood_id = :nid AND c.population > 0
                GROUP BY d.key
                """
            ),
            {"nid": nid},
        )
        return {k: v or 0.0 for k, v in rows}

    lines = [f"{round(totals.pop):,} residents"]
    if totals.age:
        lines[0] += f", median age about {round(totals.age)}"
    if totals.renters is not None:
        lines.append(f"{_pct(totals.renters)} of households rent")
    if homes := _top(await dist("housing_dist"), HOMES, 2):
        lines.append("Homes: " + ", ".join(f"{_pct(v)} {label}" for label, v in homes))
    if commutes := _top(await dist("commute_dist"), COMMUTES, 3):
        lines.append("To work: " + ", ".join(f"{_pct(v)} {label}" for label, v in commutes))
    households = await dist("household_dist")
    if households:
        big = households.get("4", 0) + households.get("5+", 0)
        lines.append(
            f"{_pct(households.get('1', 0))} of households are one person, "
            f"{_pct(big)} have four or more"
        )
    return lines


async def _developments(
    conn: AsyncConnection, nid: int
) -> tuple[int, dict[str, int], list[Development]]:
    counts = dict(
        (
            await conn.execute(
                text(
                    "SELECT application_type, count(*) FROM applications "
                    "WHERE neighbourhood_id = :nid AND date_submitted >= :since "
                    "GROUP BY 1 ORDER BY 2 DESC"
                ),
                {"nid": nid, "since": DEVELOPMENTS_SINCE},
            )
        ).all()
    )
    by_type = dict(counts)
    rows = await conn.execute(
        text(
            """
            SELECT address, date_submitted, status, description FROM applications
            WHERE neighbourhood_id = :nid AND date_submitted >= :since
              AND application_type = 'OZ' AND description IS NOT NULL
            ORDER BY date_submitted DESC LIMIT :n
            """
        ),
        {"nid": nid, "since": DEVELOPMENTS_SINCE, "n": RECENT_SHOWN},
    )
    recent = [
        Development(
            address=r.address,
            submitted=r.date_submitted.strftime("%Y-%m"),
            status=STATUSES.get(s := (r.status or "").strip().lower(), s),
            summary=_summary(r.description),
        )
        for r in rows
    ]
    return sum(counts.values()), by_type, recent


async def _places(conn: AsyncConnection, nid: int) -> tuple[list[str], list[str]]:
    params = {"nid": nid}
    nb = "(SELECT geom FROM neighbourhoods WHERE id = :nid)"
    pois = dict(
        (
            await conn.execute(
                text(
                    f"SELECT category, count(*) FROM pois "
                    f"WHERE ST_Intersects(geom, {nb}) GROUP BY 1"
                ),
                params,
            )
        ).all()
    )
    parks = (
        await conn.execute(
            text(
                f"SELECT name, area_m2 FROM parks WHERE ST_Intersects(ST_PointOnSurface(geom), "
                f"{nb}) ORDER BY area_m2 DESC NULLS LAST"
            ),
            params,
        )
    ).all()
    stops = (
        await conn.execute(
            text(
                f"SELECT mode, count(DISTINCT name) AS n, "
                f"array_agg(DISTINCT name) FILTER (WHERE mode IN ('subway', 'lrt')) AS stations "
                f"FROM transit_stops WHERE ST_Intersects(geom, {nb}) GROUP BY mode"
            ),
            params,
        )
    ).all()
    counts = [(labels, sum(pois.get(c, 0) for c in cats)) for labels, cats in PLACE_COUNTS]
    counts.insert(1, (PARKS, len(parks)))
    by_mode = {s.mode: s for s in stops}
    counts += [(labels, by_mode[mode].n) for mode, labels in TRANSIT if mode in by_mode]
    places = [f"{n} {_plural(labels, n)}" for labels, n in counts if n]
    stations = sorted(
        {n for mode in ("subway", "lrt") if mode in by_mode for n in by_mode[mode].stations or []}
    )
    anchors = [p.name for p in parks[:2] if p.name] + stations[: ANCHORS_SHOWN - 1]
    return places, anchors


async def _themes(conn: AsyncConnection, nid: int) -> tuple[list[str], int, str]:
    for scope, where in (
        ("this neighbourhood", "c.neighbourhood_id = :nid"),
        (
            f"within {NEARBY_M // 1000} km",
            "ST_DWithin(c.geom::geography, nb.geom::geography, :near)",
        ),
    ):
        rows = (
            await conn.execute(
                text(
                    f"""
                    WITH nb AS (SELECT geom FROM neighbourhoods WHERE id = :nid),
                    near AS (
                      SELECT c.id, c.themes FROM comments c, nb
                      WHERE c.themes IS NOT NULL AND {where}
                    )
                    SELECT t AS theme, count(*) AS n, (SELECT count(*) FROM near) AS total
                    FROM near, unnest(near.themes) t
                    GROUP BY t ORDER BY n DESC, t LIMIT :k
                    """
                ),
                {"nid": nid, "near": NEARBY_M, "k": THEMES_SHOWN},
            )
        ).all()
        total = rows[0].total if rows else 0
        if total >= MIN_LOCAL_COMMENTS:
            return [_theme_label(r.theme) for r in rows], total, scope
    return [], 0, ""


async def build(conn: AsyncConnection, neighbourhood_id: int) -> ContextCard | None:
    name = await conn.scalar(
        text("SELECT name FROM neighbourhoods WHERE id = :nid"), {"nid": neighbourhood_id}
    )
    if name is None:
        return None
    total, by_type, recent = await _developments(conn, neighbourhood_id)
    places, anchors = await _places(conn, neighbourhood_id)
    themes, n_comments, scope = await _themes(conn, neighbourhood_id)
    return ContextCard(
        neighbourhood_id=neighbourhood_id,
        name=name,
        people=await _people(conn, neighbourhood_id),
        developments_total=total,
        developments_by_type=by_type,
        recent_developments=recent,
        places=places,
        anchors=anchors,
        themes=themes,
        themes_comments=n_comments,
        themes_scope=scope,
    )


async def build_many(conn: AsyncConnection, ids: list[int]) -> dict[int, ContextCard]:
    cards = {}
    for nid in dict.fromkeys(ids):
        if card := await build(conn, nid):
            cards[nid] = card
    return cards
