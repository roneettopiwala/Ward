"""Drawing support: routing lines along streets, and checking drawn shapes.

Plain async functions so scripts (and the Phase 8 eval) can call them.
"""

import json
import re
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from services.catalog import GEOMETRY_TYPES, Draw, GeometryKind, catalog

# Roads a drawn shape can't sit on, and a routed line can't follow.
HIGHWAYS = ("expressway", "ramp")
# How far a shape must stay from a highway's centreline.
HIGHWAY_CLEARANCE_M = 12
# A shape counts as inside Toronto when this share of it is inside the city's
# neighbourhoods (whose boundaries follow the shoreline, so water is outside).
MIN_INSIDE_SHARE = 0.98
# A building counts as overlapped when the shape covers this share of its footprint.
OVERLAP_SHARE = 0.25
# Routing searches the street graph within this margin around the waypoints.
ROUTE_MARGIN_M = 2000
MAX_WAYPOINTS = 25


# ---------------------------------------------------------------- routing


class RouteRequest(BaseModel):
    points: list[tuple[float, float]] = Field(min_length=2, max_length=MAX_WAYPOINTS)


class Route(BaseModel):
    geometry: dict[str, Any]
    length_m: float
    streets: list[str]
    """Street names along the route, in order."""
    waypoints: list[tuple[float, float]]
    """Each clicked point moved to the street intersection the route uses."""


class RouteError(ValueError):
    pass


async def route(conn: AsyncConnection, points: list[tuple[float, float]]) -> Route:
    """The shortest street route through the points, in order, avoiding highways."""
    nodes = [await _nearest_node(conn, p) for p in points]
    edges: list[Any] = []
    for a, b in zip(nodes, nodes[1:], strict=False):
        if a.id == b.id:
            continue
        leg = await _leg(conn, a, b)
        if not leg:
            raise RouteError("No street route connects those points.")
        edges += leg
    if not edges:
        raise RouteError("Pick points farther apart.")
    lines = [json.loads(e.geometry)["coordinates"] for e in edges]
    # Each segment runs one way in the data. Start the first one at the end
    # away from the second, then turn each next one to continue the route.
    if len(lines) > 1:
        nxt = lines[1]
        far = min(_dist2(lines[0][0], nxt[0]), _dist2(lines[0][0], nxt[-1]))
        near = min(_dist2(lines[0][-1], nxt[0]), _dist2(lines[0][-1], nxt[-1]))
        if far < near:
            lines[0] = lines[0][::-1]
    coords: list[list[float]] = []
    for line in lines:
        if coords and _dist2(line[-1], coords[-1]) < _dist2(line[0], coords[-1]):
            line = line[::-1]
        coords += line[1:] if coords and _dist2(line[0], coords[-1]) < 1e-12 else line
    length = sum(e.length_m for e in edges)
    streets: list[str] = []
    for e in edges:
        if e.name and (not streets or streets[-1] != e.name):
            streets.append(e.name)
    return Route(
        geometry={"type": "LineString", "coordinates": coords},
        length_m=round(length, 1),
        streets=list(dict.fromkeys(streets)),
        waypoints=[(n.lng, n.lat) for n in nodes],
    )


async def _nearest_node(conn: AsyncConnection, point: tuple[float, float]) -> Any:
    """The street intersection nearest a point (an end of the nearest usable street)."""
    row = (
        await conn.execute(
            text(
                """
                WITH p AS (SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326) AS g),
                s AS (
                    SELECT source, target, geom FROM streets, p
                    WHERE road_class <> ALL(:highways)
                    ORDER BY geom <-> p.g LIMIT 1
                )
                SELECT CASE WHEN ST_Distance(ST_StartPoint(s.geom), p.g)
                                 <= ST_Distance(ST_EndPoint(s.geom), p.g)
                            THEN s.source ELSE s.target END AS id,
                       ST_X(CASE WHEN ST_Distance(ST_StartPoint(s.geom), p.g)
                                      <= ST_Distance(ST_EndPoint(s.geom), p.g)
                                 THEN ST_StartPoint(s.geom) ELSE ST_EndPoint(s.geom) END) AS lng,
                       ST_Y(CASE WHEN ST_Distance(ST_StartPoint(s.geom), p.g)
                                      <= ST_Distance(ST_EndPoint(s.geom), p.g)
                                 THEN ST_StartPoint(s.geom) ELSE ST_EndPoint(s.geom) END) AS lat
                FROM s, p
                """
            ),
            {"lng": point[0], "lat": point[1], "highways": list(HIGHWAYS)},
        )
    ).one_or_none()
    if row is None:
        raise RouteError("No streets near that point.")
    return row


async def _leg(conn: AsyncConnection, a: Any, b: Any) -> list[Any]:
    """Street segments on the shortest path between two intersections."""
    # pgr_dijkstra takes its edge query as text, so the bounding box is inlined;
    # it is only numbers we computed and our own constants, never user text.
    margin = ROUTE_MARGIN_M / 111_000
    w, e = min(a.lng, b.lng) - margin * 1.4, max(a.lng, b.lng) + margin * 1.4
    s, n = min(a.lat, b.lat) - margin, max(a.lat, b.lat) + margin
    highways = ", ".join(f"'{h}'" for h in HIGHWAYS)
    # Edge ids are the City's centreline ids ("street:123" -> 123).
    edges_sql = (
        "SELECT split_part(fid, ':', 2)::bigint AS id, source, target, length_m AS cost "
        f"FROM streets WHERE road_class NOT IN ({highways}) "
        f"AND geom && ST_MakeEnvelope({w:.6f}, {s:.6f}, {e:.6f}, {n:.6f}, 4326)"
    )
    rows = await conn.execute(
        text(
            """
            SELECT s.fid, s.name, s.length_m, ST_AsGeoJSON(s.geom) AS geometry
            FROM pgr_dijkstra(:edges_sql, CAST(:a AS bigint), CAST(:b AS bigint),
                              directed => false) d
            JOIN streets s ON s.fid = 'street:' || d.edge
            WHERE d.edge <> -1
            ORDER BY d.seq
            """
        ),
        {"edges_sql": edges_sql, "a": a.id, "b": b.id},
    )
    return list(rows.all())


# ---------------------------------------------------------------- validation


class ValidateRequest(BaseModel):
    geometry: dict[str, Any]
    type: str | None = None
    """A catalog type to check against; without one, any type of this geometry kind."""


class Overlap(BaseModel):
    fid: str
    name: str | None


class Validation(BaseModel):
    ok: bool
    errors: list[str]
    warnings: list[str]
    area_m2: float | None
    length_m: float | None
    overlaps: list[Overlap]
    """Buildings the shape covers; they'd be removed by a proposal here."""
    parks: list[str]
    """Parks the shape covers part of."""


async def validate(
    conn: AsyncConnection, geometry: dict[str, Any], type_name: str | None = None
) -> Validation:
    kind = _kind_of(geometry)
    if kind is None:
        raise ValueError(f"unsupported geometry: {geometry.get('type')}")
    rules = _rules(kind, type_name)
    params = {"g": json.dumps(geometry), "highways": list(HIGHWAYS)}
    m = (
        await conn.execute(
            text(
                """
                WITH g AS (SELECT ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326) AS g),
                city AS (SELECT ST_Union(geom) AS c FROM neighbourhoods
                         WHERE geom && (SELECT ST_Expand(g, 0.01) FROM g))
                SELECT ST_IsValid(g.g) AS valid,
                       ST_Area(g.g::geography) AS area,
                       ST_Length(g.g::geography) AS length,
                       CASE GeometryType(g.g)
                         WHEN 'POINT' THEN ST_Intersects(city.c, g.g)::int::float
                         WHEN 'LINESTRING' THEN
                           1 - ST_Length(ST_Difference(g.g, city.c)::geography)
                               / NULLIF(ST_Length(g.g::geography), 0)
                         ELSE ST_Area(ST_Intersection(ST_MakeValid(g.g), city.c)::geography)
                              / NULLIF(ST_Area(g.g::geography), 0)
                       END AS inside,
                       (SELECT string_agg(DISTINCT coalesce(s.name, 'a highway'), ', ')
                        FROM streets s
                        WHERE s.road_class = ANY(:highways)
                          AND ST_DWithin(s.geom::geography, g.g::geography, :clearance)
                          AND (GeometryType(g.g) <> 'LINESTRING'
                               OR ST_Length(ST_Intersection(
                                    g.g, ST_Buffer(s.geom::geography, :clearance)::geometry
                                  )::geography) > 25)
                       ) AS highways
                FROM g, city
                """
            ),
            {**params, "clearance": HIGHWAY_CLEARANCE_M},
        )
    ).one()

    errors: list[str] = []
    warnings: list[str] = []
    area = m.area if kind == "polygon" else None
    length = m.length if kind == "line" else None
    if kind == "polygon" and not m.valid:
        errors.append("The shape crosses itself. Redraw it without crossing lines.")
    if (m.inside or 0) < MIN_INSIDE_SHARE:
        errors.append("Keep it on land inside the City of Toronto.")
    if m.highways:
        errors.append(f"It can't go on {_highway_names(m.highways)}.")
    errors += _size_errors(rules, area, length)

    overlaps: list[Overlap] = []
    parks: list[str] = []
    if kind != "line" and m.valid:
        rows = await conn.execute(
            text(
                """
                WITH g AS (SELECT ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326) AS g)
                SELECT b.fid, b.name FROM buildings b, g
                WHERE ST_Intersects(b.geom, g.g)
                  AND (GeometryType(g.g) = 'POINT'
                       OR ST_Area(ST_Intersection(b.geom, g.g)) / NULLIF(ST_Area(b.geom), 0)
                          >= :share)
                ORDER BY ST_Area(b.geom) DESC
                """
            ),
            {"g": params["g"], "share": OVERLAP_SHARE},
        )
        overlaps = [Overlap(fid=r.fid, name=r.name) for r in rows]
        parks = list(
            await conn.scalars(
                text(
                    """
                    WITH g AS (SELECT ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326) AS g)
                    SELECT DISTINCT p.name FROM parks p, g
                    WHERE ST_Intersects(p.geom, g.g) AND p.name IS NOT NULL
                    """
                ),
                {"g": params["g"]},
            )
        )
    if parks:
        warnings.append(f"It covers part of {', '.join(parks[:3])}.")
    return Validation(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        area_m2=round(area, 1) if area is not None else None,
        length_m=round(length, 1) if length is not None else None,
        overlaps=overlaps,
        parks=parks,
    )


def _highway_names(raw: str) -> str:
    """'F G Gardiner Xy W, Spadina S Gardiner Ramp' -> 'the Gardiner Expressway'."""
    names: list[str] = []
    for name in raw.split(", "):
        if "Gardiner" in name:
            nice = "the Gardiner Expressway"
        elif "Don Valley" in name or name.startswith("Dvp"):
            nice = "the Don Valley Parkway"
        elif name.startswith("Qew"):
            nice = "the QEW"
        elif match := re.search(r"\b(2a|400|401|404|409|427)\b", name):
            nice = f"Highway {match.group(1).upper()}"
        elif name.endswith("Ramp"):
            nice = "a highway ramp"
        else:
            nice = name
        if nice not in names:
            names.append(nice)
    # A ramp is only worth naming when nothing bigger is.
    if len(names) > 1 and "a highway ramp" in names:
        names.remove("a highway ramp")
    return " or ".join(names)


def _dist2(a: list[float], b: list[float]) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _kind_of(geometry: dict[str, Any]) -> GeometryKind | None:
    return next((k for k, types in GEOMETRY_TYPES.items() if geometry.get("type") in types), None)


def _rules(kind: GeometryKind, type_name: str | None) -> Draw | None:
    """The type's draw rules, or the loosest limits across types of this kind."""
    types = catalog()
    if type_name:
        t = types.get(type_name)
        if t is None:
            raise ValueError(f"unknown type {type_name!r}")
        return t.draw
    same = [t.draw for t in types.values() if t.geometry == kind]
    if not same:
        return None

    def loosest(values: list[float | None], pick: Any) -> float | None:
        known = [v for v in values if v is not None]
        return pick(known) if len(known) == len(values) else None

    return Draw(
        tools=sorted({tool for d in same for tool in d.tools}),
        min_area_m2=loosest([d.min_area_m2 for d in same], min),
        max_area_m2=loosest([d.max_area_m2 for d in same], max),
        min_length_m=loosest([d.min_length_m for d in same], min),
        max_length_m=loosest([d.max_length_m for d in same], max),
    )


def _size_errors(rules: Draw | None, area: float | None, length: float | None) -> list[str]:
    if rules is None:
        return []
    errors = []
    if area is not None:
        if rules.min_area_m2 and area < rules.min_area_m2:
            errors.append(f"Too small: at least {_m2(rules.min_area_m2)}.")
        if rules.max_area_m2 and area > rules.max_area_m2:
            errors.append(f"Too big: at most {_m2(rules.max_area_m2)}.")
    if length is not None:
        if rules.min_length_m and length < rules.min_length_m:
            errors.append(f"Too short: at least {rules.min_length_m:,.0f} m.")
        if rules.max_length_m and length > rules.max_length_m:
            errors.append(f"Too long: at most {rules.max_length_m / 1000:,.1f} km.")
    return errors


def _m2(value: float) -> str:
    return f"{value / 10_000:,.1f} ha" if value >= 10_000 else f"{value:,.0f} m²"
