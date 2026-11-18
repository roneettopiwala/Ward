"""Area resolver: which neighbourhoods and census areas a proposal affects.

The impact area is the proposal's geometry (area, line or point) grown by its
impact radius. Each neighbourhood is weighted by the people living in the
part of it inside the impact area, the same overlap weighting the fact sheet
uses for census values. Plain async functions so scripts can call them.
"""

import json
from typing import Any

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


class NeighbourhoodShare(BaseModel):
    id: int
    name: str
    residents: float
    """People living in the part of this neighbourhood inside the impact area."""
    share: float
    """Their share of everyone in the impact area (0 to 1)."""
    contains_site: bool


class ImpactArea(BaseModel):
    radius_m: float
    neighbourhoods: list[NeighbourhoodShare]
    """Neighbourhoods with census data, most residents in the impact area first."""
    dguids: list[str]
    """Census dissemination areas the impact area overlaps."""
    residents: float
    missing: list[str]
    """Neighbourhoods the impact area touches that have no city data loaded yet."""


async def resolve(conn: AsyncConnection, geometry: dict[str, Any], radius_m: float) -> ImpactArea:
    params = {"g": json.dumps(geometry), "r": radius_m}
    site = """
        WITH site AS (
            SELECT g, ST_Buffer(g::geography, :r)::geometry AS ring
            FROM (SELECT ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326) AS g) s
        )
    """
    das = (
        await conn.execute(
            text(
                site
                + """
                SELECT c.dguid, c.neighbourhood_id,
                       coalesce(c.population, 0)
                         * ST_Area(ST_Intersection(c.geom, site.ring)::geography)
                         / NULLIF(ST_Area(c.geom::geography), 0) AS people
                FROM census_areas c, site
                WHERE ST_Intersects(c.geom, site.ring)
                """
            ),
            params,
        )
    ).all()
    hoods = (
        await conn.execute(
            text(
                site
                + """
                SELECT n.id, n.name, ST_Intersects(n.geom, ST_PointOnSurface(site.g)) AS has_site,
                       EXISTS (SELECT 1 FROM census_areas c WHERE c.neighbourhood_id = n.id)
                         AS loaded
                FROM neighbourhoods n, site
                WHERE ST_Intersects(n.geom, site.ring)
                """
            ),
            params,
        )
    ).all()

    people: dict[int, float] = {}
    for d in das:
        people[d.neighbourhood_id] = people.get(d.neighbourhood_id, 0.0) + float(d.people or 0)
    total = sum(people.values())
    shares = [
        NeighbourhoodShare(
            id=h.id,
            name=h.name,
            residents=round(people.get(h.id, 0.0), 1),
            share=round(people.get(h.id, 0.0) / total, 4) if total else 0.0,
            contains_site=bool(h.has_site),
        )
        for h in hoods
        if h.loaded
    ]
    shares.sort(key=lambda s: (-s.contains_site, -s.residents, s.id))
    return ImpactArea(
        radius_m=radius_m,
        neighbourhoods=shares,
        dguids=sorted(d.dguid for d in das),
        residents=round(total, 1),
        missing=sorted(h.name for h in hoods if not h.loaded),
    )


# Places that draw people from across the city, so citywide personas join.
LANDMARK_KINDS = [
    "attraction", "stadium", "theatre", "museum", "aquarium", "arts_centre", "gallery",
    "zoo", "marina",
]  # fmt: skip


async def landmarks(conn: AsyncConnection, geometry: dict[str, Any]) -> list[str]:
    """Names of city-scale places the proposal's site covers."""
    return list(
        (
            await conn.execute(
                text(
                    """
                    SELECT DISTINCT name FROM pois
                    WHERE category = ANY(:kinds) AND name IS NOT NULL
                      AND ST_Intersects(geom, ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326))
                    ORDER BY name
                    """
                ),
                {"kinds": LANDMARK_KINDS, "g": json.dumps(geometry)},
            )
        ).scalars()
    )


def persona_seats(area: ImpactArea, total: int, max_neighbourhoods: int = 3) -> dict[int, int]:
    """How many of the reacting personas come from each neighbourhood.

    The site's own neighbourhood always takes part; other neighbourhoods join
    when enough of the impact area's residents live there, and seats follow
    their share of residents.
    """
    if not area.neighbourhoods:
        return {}
    picked = [area.neighbourhoods[0]] + [
        n for n in area.neighbourhoods[1:] if n.share >= MIN_SHARE
    ][: max_neighbourhoods - 1]
    weight = {n.id: max(n.share, MIN_SHARE) for n in picked}
    scale = total / sum(weight.values())
    seats = {nid: max(MIN_SEATS, round(w * scale)) for nid, w in weight.items()}
    # Fix rounding so the seats add up exactly; the site's neighbourhood absorbs it.
    first = picked[0].id
    seats[first] = max(MIN_SEATS, seats[first] + total - sum(seats.values()))
    while sum(seats.values()) > total:
        biggest = max((n for n in seats if n != first), key=lambda n: seats[n], default=first)
        seats[biggest] -= 1
    return seats


# A neighbourhood joins when this share of the impact area's residents live there.
MIN_SHARE = 0.15
# Fewest personas a taking-part neighbourhood gets, so its view is heard.
MIN_SEATS = 3
