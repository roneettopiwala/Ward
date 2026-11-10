"""Personal impact: what a proposal means for one persona, computed in code.

Distances from their home and routine places to the site, which of those
places are inside the impact area, which would be lost, and how their commute
touches the site. The reaction prompt gets these facts; the LLM never
estimates distances itself.
"""

import json
import uuid

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from services.personas import PLACES_SQL, Persona


class PlaceImpact(BaseModel):
    fid: str
    name: str
    kind: str
    relation: str
    distance_m: float
    within: bool
    """Inside the impact radius."""
    lost: bool
    """Replaced by, or sitting on, the proposal's site."""


class PersonalImpact(BaseModel):
    persona_id: uuid.UUID
    home_distance_m: float
    pin: tuple[float, float]
    """Where the persona shows on the map: home for residents, else their nearest place."""
    pin_distance_m: float
    places: list[PlaceImpact]
    bullets: list[str]
    """Plain statements for the prompt and the card's "What shapes this view"."""


def km(m: float) -> str:
    return "under 0.1 km" if m < 100 else f"{m / 1000:.1f} km"


async def compute(
    conn: AsyncConnection,
    personas: list[Persona],
    geometry: dict,
    replaces: list[str],
    radius_m: float,
) -> dict[uuid.UUID, PersonalImpact]:
    ids = [p.id for p in personas]
    params = {"g": json.dumps(geometry), "ids": ids, "replaces": replaces}
    site = "(SELECT ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326) AS g) site"
    homes = {
        r.id: r.d
        for r in await conn.execute(
            text(
                f"SELECT p.id, ST_Distance(p.home::geography, site.g::geography) AS d "
                f"FROM personas p, {site} WHERE p.id = ANY(:ids)"
            ),
            params,
        )
    }
    place_rows = await conn.execute(
        text(
            f"""
            WITH {PLACES_SQL}
            SELECT pp.persona_id, pp.place_fid,
                   ST_Distance(pl.geom::geography, site.g::geography) AS d,
                   pp.place_fid = ANY(:replaces)
                       OR ST_Intersects(pl.geom, site.g)
                       OR EXISTS (SELECT 1 FROM parks k WHERE k.fid = pp.place_fid
                                  AND ST_Intersects(k.geom, site.g)) AS lost
            FROM persona_places pp
            JOIN places pl ON pl.fid = pp.place_fid, {site}
            WHERE pp.persona_id = ANY(:ids)
            """
        ),
        params,
    )
    by_place = {(r.persona_id, r.place_fid): (r.d, r.lost) for r in place_rows}

    out: dict[uuid.UUID, PersonalImpact] = {}
    for p in personas:
        places = []
        for pl in p.places:
            d, lost = by_place.get((p.id, pl.fid), (None, False))
            if d is None:
                continue
            places.append(
                PlaceImpact(
                    fid=pl.fid,
                    name=pl.name,
                    kind=pl.kind,
                    relation=pl.relation,
                    distance_m=round(d),
                    within=d <= radius_m,
                    lost=bool(lost),
                )
            )
        home_d = round(homes[p.id])
        if p.role == "resident" or not places:
            pin, pin_d = p.home, home_d
        else:
            nearest = min(places, key=lambda x: x.distance_m)
            pin = next(x.lnglat for x in p.places if x.fid == nearest.fid)
            pin_d = nearest.distance_m
        out[p.id] = PersonalImpact(
            persona_id=p.id,
            home_distance_m=home_d,
            pin=pin,
            pin_distance_m=pin_d,
            places=places,
            bullets=_bullets(p, home_d, places, radius_m),
        )
    return out


def _bullets(p: Persona, home_d: float, places: list[PlaceImpact], radius_m: float) -> list[str]:
    """Most important first: places they'd lose, where they live, places nearby, commute."""

    def use(pl: PlaceImpact) -> str:
        return pl.relation[0].upper() + pl.relation[1:] + " " + pl.name

    ordered = sorted(places, key=lambda x: x.distance_m)
    out = [f"{use(pl)}, which this proposal would replace or build on" for pl in ordered if pl.lost]
    if p.role == "resident":
        where = "inside" if home_d <= radius_m else "outside"
        out.append(f"Lives {km(home_d)} from the site, {where} the {radius_m:.0f} m impact area")
    else:
        out.append(f"Lives in another neighbourhood, {km(home_d)} from the site")
    out += [f"{use(pl)}, {km(pl.distance_m)} from the site" for pl in ordered
            if pl.within and not pl.lost]  # fmt: skip
    if not any(pl.within for pl in places):
        out.append(f"None of their regular places are within {radius_m:.0f} m of the site")
    if p.commute_mode and p.commute_mode != "other":
        mode = {"car": "drives", "transit": "takes transit", "walk": "walks", "bike": "bikes"}
        out.append(f"Usually {mode[p.commute_mode]} to work or school")
    return out
