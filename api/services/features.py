"""Details for base-map features by fid. Plain async functions so scripts can call them.

Every map layer has a kind, given by its fid prefix ("building:…", "park:…").
Areas (buildings, parcels, parks) can be replaced by a proposal; lines and
points (streets, cycling, transit stops) are shown for information.
"""

import json
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

NEAREST_STOPS = 3
# A parcel counts as part of a building's lot when the building covers this share of it.
LOT_SHARE = 0.5

Kind = Literal["building", "parcel", "park", "transit", "cycling", "street"]
KINDS: tuple[Kind, ...] = ("building", "parcel", "park", "transit", "cycling", "street")


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
    kind: Kind
    name: str | None
    use: str | None = None
    height_m: float | None = None
    address: str | None = None
    lot_area_m2: float | None = None
    """For a building, its lot; for a parcel or park, its own area."""
    zoning: Zoning | None = None
    """None where By-law 569-2013 does not apply (no open zoning data)."""
    nearest_stops: list[TransitStop] = []
    # Lines and points.
    mode: str | None = None
    routes: list[str] = []
    road_class: str | None = None
    facility_type: str | None = None
    installed: int | None = None
    length_m: float | None = None
    geometry: dict[str, Any]


def kind_of(fid: str) -> Kind | None:
    prefix = fid.split(":", 1)[0]
    return prefix if prefix in KINDS else None  # type: ignore[return-value]


async def detail(conn: AsyncConnection, fid: str) -> FeatureDetail | None:
    kind = kind_of(fid)
    if kind == "building":
        return await _building(conn, fid)
    if kind in ("parcel", "park"):
        return await _area(conn, fid, kind)
    if kind == "transit":
        return await _transit(conn, fid)
    if kind == "cycling":
        return await _line(conn, fid, kind, "cycling")
    if kind == "street":
        return await _line(conn, fid, kind, "streets")
    return None


async def _building(conn: AsyncConnection, fid: str) -> FeatureDetail | None:
    row = (
        await conn.execute(
            text(
                """
                SELECT b.fid, b.name, b.use, b.height_m, ST_AsGeoJSON(b.geom) AS geometry,
                       p.address, p.area_m2
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
                WHERE b.fid = :fid
                """
            ),
            {"fid": fid, "lot_share": LOT_SHARE},
        )
    ).one_or_none()
    if row is None:
        return None
    return FeatureDetail(
        fid=row.fid,
        kind="building",
        name=row.name,
        use=row.use,
        height_m=_round(row.height_m),
        address=row.address,
        lot_area_m2=_round(row.area_m2),
        zoning=await _zoning(conn, "buildings", fid),
        nearest_stops=await _stops(conn, "buildings", fid),
        geometry=json.loads(row.geometry),
    )


async def _area(conn: AsyncConnection, fid: str, kind: Kind) -> FeatureDetail | None:
    table = "parcels" if kind == "parcel" else "parks"
    label = "address" if kind == "parcel" else "name"
    row = (
        await conn.execute(
            text(
                f"SELECT fid, {label} AS label, area_m2, ST_AsGeoJSON(geom) AS geometry "
                f"FROM {table} WHERE fid = :fid"
            ),
            {"fid": fid},
        )
    ).one_or_none()
    if row is None:
        return None
    return FeatureDetail(
        fid=row.fid,
        kind=kind,
        name=row.label if kind == "park" else None,
        use="park" if kind == "park" else "lot",
        address=row.label if kind == "parcel" else None,
        lot_area_m2=_round(row.area_m2),
        zoning=await _zoning(conn, table, fid),
        nearest_stops=await _stops(conn, table, fid),
        geometry=json.loads(row.geometry),
    )


async def _transit(conn: AsyncConnection, fid: str) -> FeatureDetail | None:
    row = (
        await conn.execute(
            text(
                "SELECT fid, name, mode, routes, ST_AsGeoJSON(geom) AS geometry "
                "FROM transit_stops WHERE fid = :fid"
            ),
            {"fid": fid},
        )
    ).one_or_none()
    if row is None:
        return None
    return FeatureDetail(
        fid=row.fid,
        kind="transit",
        name=row.name,
        mode=row.mode,
        routes=row.routes or [],
        geometry=json.loads(row.geometry),
    )


async def _line(conn: AsyncConnection, fid: str, kind: Kind, table: str) -> FeatureDetail | None:
    extra = (
        "road_class, NULL AS facility_type, NULL::int AS installed"
        if table == "streets"
        else "NULL AS road_class, facility_type, installed"
    )
    row = (
        await conn.execute(
            text(
                f"SELECT fid, name, {extra}, ST_Length(geom::geography) AS length_m, "
                f"ST_AsGeoJSON(geom) AS geometry FROM {table} WHERE fid = :fid"
            ),
            {"fid": fid},
        )
    ).one_or_none()
    if row is None:
        return None
    return FeatureDetail(
        fid=row.fid,
        kind=kind,
        name=row.name,
        road_class=row.road_class,
        facility_type=row.facility_type,
        installed=row.installed,
        length_m=round(row.length_m, 1),
        geometry=json.loads(row.geometry),
    )


async def _zoning(conn: AsyncConnection, table: str, fid: str) -> Zoning | None:
    row = (
        await conn.execute(
            text(
                f"""
                SELECT z.zone_code, z.zone_class, z.max_height_m
                FROM {table} f JOIN zoning z ON ST_Intersects(z.geom, ST_PointOnSurface(f.geom))
                WHERE f.fid = :fid LIMIT 1
                """
            ),
            {"fid": fid},
        )
    ).one_or_none()
    if row is None:
        return None
    return Zoning(
        code=row.zone_code, zone_class=row.zone_class, max_height_m=_round(row.max_height_m)
    )


async def _stops(conn: AsyncConnection, table: str, fid: str) -> list[TransitStop]:
    rows = await conn.execute(
        text(
            f"""
            SELECT s.fid, s.name, s.mode, s.routes,
                   ST_Distance(s.geom::geography, f.geom::geography) AS distance_m
            FROM {table} f
            CROSS JOIN LATERAL (
                SELECT * FROM transit_stops ORDER BY geom <-> f.geom LIMIT 20
            ) s
            WHERE f.fid = :fid
            ORDER BY distance_m
            LIMIT :n
            """
        ),
        {"fid": fid, "n": NEAREST_STOPS},
    )
    return [
        TransitStop(
            fid=s.fid,
            name=s.name,
            mode=s.mode,
            routes=s.routes or [],
            distance_m=round(s.distance_m, 1),
        )
        for s in rows
    ]


def _round(value: float | None) -> float | None:
    """REAL columns come back as float32 noise (88.0999...)."""
    return round(value, 1) if value is not None else None
