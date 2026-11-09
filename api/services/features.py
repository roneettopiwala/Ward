"""Spatial lookups for base-map features. Plain async functions so scripts can call them."""

import json
from typing import Any

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

NEAREST_STOPS = 3
# How far from a click we still accept a building (covers small mismatches
# between the basemap's footprints and ours).
SNAP_M = 8
# A parcel counts as part of a building's lot when the building covers this share of it.
LOT_SHARE = 0.5


class Zoning(BaseModel):
    code: str
    zone_class: str | None
    max_height_m: float | None


class TransitStop(BaseModel):
    fid: str
    name: str | None
    mode: str | None
    routes: list[str]
    distance_m: float


class FeatureDetail(BaseModel):
    fid: str
    name: str | None
    use: str | None
    height_m: float | None
    address: str | None
    lot_area_m2: float | None
    zoning: Zoning | None
    """None where By-law 569-2013 does not apply (no open zoning data)."""
    nearest_stops: list[TransitStop]
    footprint: dict[str, Any]


async def building_at(conn: AsyncConnection, lng: float, lat: float) -> str | None:
    row = await conn.execute(
        text(
            """
            WITH pt AS (SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326) AS g)
            SELECT fid FROM buildings, pt
            WHERE ST_DWithin(geom::geography, pt.g::geography, :snap)
            ORDER BY ST_Intersects(geom, pt.g) DESC, geom <-> pt.g
            LIMIT 1
            """
        ),
        {"lng": lng, "lat": lat, "snap": SNAP_M},
    )
    return row.scalar_one_or_none()


async def in_loaded_area(conn: AsyncConnection, lng: float, lat: float) -> bool:
    row = await conn.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM neighbourhoods "
            "WHERE ST_Intersects(geom, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)))"
        ),
        {"lng": lng, "lat": lat},
    )
    return bool(row.scalar_one())


async def building_detail(conn: AsyncConnection, fid: str) -> FeatureDetail | None:
    row = (
        await conn.execute(
            text(
                """
                SELECT b.fid, b.name, b.use, b.height_m, ST_AsGeoJSON(b.geom) AS footprint,
                       p.address, p.area_m2,
                       z.zone_code, z.zone_class, z.max_height_m
                FROM buildings b
                -- The lot: every parcel mostly under the building (big sites span
                -- several), else the parcel the building overlaps most.
                LEFT JOIN LATERAL (
                    WITH o AS (
                        SELECT address, area_m2,
                               ST_Area(ST_Intersection(geom, b.geom)) AS overlap,
                               ST_Area(ST_Intersection(geom, b.geom)) / ST_Area(geom) AS share
                        FROM parcels WHERE ST_Intersects(geom, b.geom)
                    )
                    SELECT
                        COALESCE(
                            (SELECT sum(area_m2) FROM o WHERE share >= :lot_share),
                            (SELECT area_m2 FROM o ORDER BY overlap DESC LIMIT 1)
                        ) AS area_m2,
                        (SELECT address FROM o WHERE address IS NOT NULL
                         ORDER BY overlap DESC LIMIT 1) AS address
                ) p ON true
                LEFT JOIN LATERAL (
                    SELECT zone_code, zone_class, max_height_m FROM zoning
                    WHERE ST_Intersects(zoning.geom, ST_PointOnSurface(b.geom))
                    LIMIT 1
                ) z ON true
                WHERE b.fid = :fid
                """
            ),
            {"fid": fid, "lot_share": LOT_SHARE},
        )
    ).one_or_none()
    if row is None:
        return None

    stops = await conn.execute(
        text(
            """
            SELECT s.fid, s.name, s.mode, s.routes,
                   ST_Distance(s.geom::geography, b.geom::geography) AS distance_m
            FROM transit_stops s, buildings b
            WHERE b.fid = :fid
            ORDER BY distance_m
            LIMIT :n
            """
        ),
        {"fid": fid, "n": NEAREST_STOPS},
    )
    return FeatureDetail(
        fid=row.fid,
        name=row.name,
        use=row.use,
        height_m=_round(row.height_m),
        address=row.address,
        lot_area_m2=_round(row.area_m2),
        zoning=(
            Zoning(
                code=row.zone_code,
                zone_class=row.zone_class,
                max_height_m=_round(row.max_height_m),
            )
            if row.zone_code
            else None
        ),
        nearest_stops=[
            TransitStop(
                fid=s.fid,
                name=s.name,
                mode=s.mode,
                routes=s.routes or [],
                distance_m=round(s.distance_m, 1),
            )
            for s in stops
        ],
        footprint=json.loads(row.footprint),
    )


def _round(value: float | None) -> float | None:
    """REAL columns come back as float32 noise (88.0999...)."""
    return round(value, 1) if value is not None else None
