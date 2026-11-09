"""The fact sheet: every number about a proposal, computed with PostGIS.

Each metric named in a type's `impact_metrics` is one function here. The LLM
only ever phrases these facts; it never produces numbers of its own.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from services.catalog import TypeDef

NEIGHBOUR_RADIUS_M = 250
SUBWAY_SEARCH_M = 1500
NOT_IN_BYLAW = "Not in By-law 569-2013"
# OSM categories counted as shops, restaurants and other everyday retail.
RETAIL_CATEGORIES = [
    "fast_food", "restaurant", "cafe", "clothes", "convenience", "grocery", "shoes",
    "mobile_phone", "pharmacy", "bakery", "jewelry", "cosmetics", "bar", "pub", "ice_cream",
    "mall", "department_store", "electronics", "books", "gift", "optician", "beauty",
    "hairdresser", "supermarket", "variety_store", "furniture", "sports", "toys",
]  # fmt: skip
# Zone classes (By-law 569-2013) whose permitted uses broadly include each type.
ZONE_FITS = {
    "condo": {
        "residential", "residential apartment", "commercial residential",
        "commercial residential employment",
    },
    "mall": {"commercial residential", "commercial residential employment", "commercial local"},
    "park": {"open space"},
}  # fmt: skip

SOURCE_PROPOSAL = "Your proposal"
SOURCE_MASSING = "City 3D massing"
SOURCE_ZONING = "Zoning By-law 569-2013"
SOURCE_TTC = "TTC network"
SOURCE_PARKS = "City parkland data"
SOURCE_OSM = "OpenStreetMap"
SOURCE_CENSUS = "2021 Census"


class Fact(BaseModel):
    id: str
    label: str
    value: float | str | list[str] | None
    unit: str | None = None
    display: str
    """The value as it should read, e.g. "12 stops". Pros/cons quote this."""
    source: str


class FactSheet(BaseModel):
    type: str
    type_label: str
    params: dict[str, float]
    impact_radius_m: float
    site_name: str
    facts: list[Fact]

    def by_id(self) -> dict[str, Fact]:
        return {f.id: f for f in self.facts}


class ProposalInput(BaseModel):
    """What analysis needs: the structured proposal, no ids or UI state."""

    type: str
    params: dict[str, float]
    geometry: dict[str, Any]
    replaces: list[str] = []


@dataclass
class Context:
    conn: AsyncConnection
    proposal: ProposalInput
    typedef: TypeDef
    facts: list[Fact] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)
    """Intermediate numbers later metrics build on (population, park area...)."""

    @property
    def radius(self) -> float:
        return self.typedef.impact_radius_m

    @property
    def height_m(self) -> float | None:
        param = self.typedef.render.height_param
        return self.proposal.params.get(param) if param else None

    def add(
        self,
        id: str,
        label: str,
        value: float | str | list[str] | None,
        source: str,
        unit: str | None = None,
        display: str | None = None,
    ) -> None:
        if isinstance(value, float):
            value = round(value, 1)
        shown = display if display is not None else _display(value, unit)
        self.facts.append(
            Fact(id=id, label=label, value=value, unit=unit, display=shown, source=source)
        )

    async def row(self, sql: str, **params: Any) -> Any:
        return (await self.conn.execute(text(_SITE + sql), self._bind(params))).one_or_none()

    async def rows(self, sql: str, **params: Any) -> list[Any]:
        return list((await self.conn.execute(text(_SITE + sql), self._bind(params))).all())

    def _bind(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "geojson": json.dumps(self.proposal.geometry),
            "replaces": self.proposal.replaces,
            "radius": self.radius,
            **params,
        }


# Every metric query starts from the proposal's geometry and impact area.
_SITE = """
WITH site AS (
    SELECT g, ST_Buffer(g::geography, :radius)::geometry AS ring
    FROM (SELECT ST_SetSRID(ST_GeomFromGeoJSON(:geojson), 4326) AS g) s
)
"""


def _display(value: float | str | list[str] | None, unit: str | None) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, list):
        return ", ".join(value) if value else "none"
    if isinstance(value, str):
        return value
    number = f"{value:,.0f}" if abs(value) >= 100 or value == int(value) else f"{value:,.1f}"
    if unit and value == 1 and unit.endswith("s") and "," not in unit:
        unit = unit.removesuffix("s")  # 1 school, 1 storey
    return f"{number} {unit}" if unit else number


async def replaced(ctx: Context) -> None:
    rows = await ctx.rows(
        """
        SELECT name, use, height_m, ST_Area(geom::geography) AS area
        FROM buildings WHERE fid = ANY(:replaces)
        """
    )
    if not rows:
        if not ctx.proposal.replaces:
            ctx.add("replaced.none", "Replaces", "nothing (empty site)", SOURCE_PROPOSAL)
        return
    ctx.add(
        "replaced.name", "Replaces", ", ".join(r.name or "a building" for r in rows), SOURCE_MASSING
    )
    uses = sorted({r.use for r in rows if r.use})
    if uses:
        ctx.add("replaced.use", "Current use", ", ".join(uses), SOURCE_OSM)
    heights = [r.height_m for r in rows if r.height_m]
    if heights:
        ctx.add("replaced.height_m", "Current building height", max(heights), SOURCE_MASSING, "m")
    ctx.add(
        "replaced.footprint_m2",
        "Current building footprint",
        sum(r.area for r in rows),
        SOURCE_MASSING,
        "m²",
    )


async def site(ctx: Context) -> None:
    r = await ctx.row(
        """
        SELECT ST_Area(site.g::geography) AS area,
               (SELECT name FROM neighbourhoods n
                WHERE ST_Intersects(n.geom, ST_PointOnSurface(site.g)) LIMIT 1) AS hood
        FROM site
        """
    )
    ctx.values["site_area"] = r.area
    ctx.add("site.area_m2", "Site area", r.area, SOURCE_PROPOSAL, "m²")
    if r.hood:
        ctx.add("site.neighbourhood", "Neighbourhood", r.hood, SOURCE_PROPOSAL)
    if ctx.height_m is not None:
        ctx.add("proposal.height_m", "Proposed height", ctx.height_m, SOURCE_PROPOSAL, "m")
        if ctx.typedef.storey_m:
            storeys = max(1, round(ctx.height_m / ctx.typedef.storey_m))
            ctx.values["storeys"] = storeys
            ctx.add("proposal.storeys", "Proposed storeys", storeys, SOURCE_PROPOSAL, "storeys")


async def zoning_fit(ctx: Context) -> None:
    r = await ctx.row(
        """
        SELECT z.zone_code, z.zone_class, z.max_height_m FROM site, zoning z
        WHERE ST_Intersects(z.geom, ST_PointOnSurface(site.g)) LIMIT 1
        """
    )
    if r is None:
        ctx.add(
            "zoning.code",
            "Zoning",
            NOT_IN_BYLAW,
            SOURCE_ZONING,
            display=f"{NOT_IN_BYLAW} (older site-specific by-law; no open data to check against)",
        )
        return
    ctx.add("zoning.code", "Zoning", r.zone_code, SOURCE_ZONING)
    if r.zone_class:
        ctx.add("zoning.class", "Zone class", r.zone_class, SOURCE_ZONING)
        fits = r.zone_class in ZONE_FITS.get(ctx.typedef.type, set())
        ctx.add(
            "zoning.use_fits",
            f"Zone class broadly permits a {ctx.typedef.label.lower()}",
            "yes" if fits else "no",
            SOURCE_ZONING,
        )
    if r.max_height_m and ctx.height_m is not None:
        ctx.add("zoning.max_height_m", "Zoning height limit", r.max_height_m, SOURCE_ZONING, "m")
        over = ctx.height_m - r.max_height_m
        if over > 0:
            ctx.add("zoning.over_limit_m", "Height over the zoning limit", over, SOURCE_ZONING, "m")
        else:
            ctx.add("zoning.within_limit", "Within the zoning height limit", "yes", SOURCE_ZONING)


async def height_context(ctx: Context) -> None:
    r = await ctx.row(
        """
        SELECT count(*) AS n,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY height_m) AS median,
               max(height_m) AS tallest,
               (array_agg(name ORDER BY height_m DESC))[1] AS tallest_name
        FROM buildings b, site
        WHERE ST_DWithin(b.geom::geography, site.g::geography, :near)
          AND NOT b.fid = ANY(:replaces) AND b.height_m > 0
        """,
        near=NEIGHBOUR_RADIUS_M,
    )
    if not r.n:
        return
    within = f"within {NEIGHBOUR_RADIUS_M} m"
    ctx.add("neighbours.count", f"Buildings {within}", r.n, SOURCE_MASSING, "buildings")
    ctx.add(
        "neighbours.median_height_m",
        f"Median building height {within}",
        r.median,
        SOURCE_MASSING,
        "m",
    )
    ctx.add("neighbours.tallest_m", f"Tallest building {within}", r.tallest, SOURCE_MASSING, "m")
    if r.tallest_name:
        ctx.add(
            "neighbours.tallest_name", f"Tallest building {within}", r.tallest_name, SOURCE_MASSING
        )
    if ctx.height_m and r.median:
        ratio = ctx.height_m / r.median
        ctx.add(
            "proposal.height_vs_median",
            f"Proposed height vs. median {within}",
            round(ratio, 1),
            SOURCE_MASSING,
            display=f"{ratio:.1f}× the median",
        )
        taller = ctx.height_m > r.tallest
        ctx.add(
            "proposal.tallest_nearby",
            f"Would be the tallest building {within}",
            "yes" if taller else "no",
            SOURCE_MASSING,
        )


async def transit(ctx: Context) -> None:
    r = await ctx.row(
        """
        SELECT count(DISTINCT s.name) AS stops,
               array(SELECT DISTINCT unnest(s2.routes) FROM transit_stops s2, site
                     WHERE ST_DWithin(s2.geom::geography, site.g::geography, :radius)
                     ORDER BY 1) AS routes
        FROM transit_stops s, site
        WHERE ST_DWithin(s.geom::geography, site.g::geography, :radius)
        """
    )
    within = f"within {ctx.radius:g} m"
    ctx.add("transit.stops", f"TTC stops {within}", r.stops, SOURCE_TTC, "stops")
    ctx.add("transit.routes", f"TTC routes {within}", r.routes, SOURCE_TTC)
    nearest = await ctx.row(
        """
        SELECT s.name, s.mode, ST_Distance(s.geom::geography, site.g::geography) AS d
        FROM transit_stops s, site ORDER BY d LIMIT 1
        """
    )
    if nearest:
        ctx.add("transit.nearest_name", "Nearest TTC stop", nearest.name, SOURCE_TTC)
        ctx.add("transit.nearest_m", "Distance to nearest TTC stop", nearest.d, SOURCE_TTC, "m")
    subway = await ctx.row(
        """
        SELECT s.name, ST_Distance(s.geom::geography, site.g::geography) AS d
        FROM transit_stops s, site WHERE s.mode = 'subway'
        ORDER BY d LIMIT 1
        """
    )
    if subway and subway.d <= SUBWAY_SEARCH_M:
        ctx.add("transit.subway_name", "Nearest subway station", _station(subway.name), SOURCE_TTC)
        ctx.add("transit.subway_m", "Distance to nearest subway station", subway.d, SOURCE_TTC, "m")
    else:
        ctx.add(
            "transit.subway_m",
            "Nearest subway station",
            None,
            SOURCE_TTC,
            display=f"none within {SUBWAY_SEARCH_M / 1000:g} km",
        )


async def parks(ctx: Context) -> None:
    r = await ctx.row(
        """
        SELECT count(*) AS n,
               coalesce(sum(ST_Area(ST_Intersection(p.geom, site.ring)::geography)), 0) AS area
        FROM parks p, site WHERE ST_Intersects(p.geom, site.ring)
        """
    )
    ctx.values["park_area"] = r.area
    within = f"within {ctx.radius:g} m"
    ctx.add("parks.count", f"Parks {within}", r.n, SOURCE_PARKS, "parks")
    ctx.add("parks.area_m2", f"Park area {within}", r.area, SOURCE_PARKS, "m²")
    nearest = await ctx.row(
        """
        SELECT p.name, ST_Distance(p.geom::geography, site.g::geography) AS d
        FROM parks p, site ORDER BY p.geom <-> site.g LIMIT 1
        """
    )
    if nearest:
        ctx.add("parks.nearest_name", "Nearest park", nearest.name, SOURCE_PARKS)
        ctx.add("parks.nearest_m", "Distance to nearest park", nearest.d, SOURCE_PARKS, "m")
    if ctx.typedef.type == "park":
        added = ctx.values["site_area"]
        ctx.add("proposal.park_area_m2", "New park area", added, SOURCE_PROPOSAL, "m²")
        if r.area:
            ctx.add(
                "parks.area_increase_pct",
                f"Increase in park area {within}",
                added / r.area * 100,
                SOURCE_PARKS,
                "%",
                display=f"{added / r.area * 100:.0f}%",
            )


async def schools(ctx: Context) -> None:
    await _nearby(ctx, "schools", "Schools", ["school", "kindergarten"])


async def groceries(ctx: Context) -> None:
    await _nearby(ctx, "groceries", "Grocery stores", ["grocery", "supermarket"])


async def retail_nearby(ctx: Context) -> None:
    await _nearby(ctx, "retail", "Shops, cafés and restaurants", RETAIL_CATEGORIES, nearest=False)
    await _nearby(ctx, "malls", "Malls", ["mall", "department_store"])


async def _nearby(
    ctx: Context, key: str, label: str, categories: list[str], nearest: bool = True
) -> None:
    r = await ctx.row(
        """
        SELECT count(*) AS n FROM pois p, site
        WHERE p.category = ANY(:cats)
          AND ST_DWithin(p.geom::geography, site.g::geography, :radius)
        """,
        cats=categories,
    )
    ctx.add(f"{key}.count", f"{label} within {ctx.radius:g} m", r.n, SOURCE_OSM, label.lower())
    if not nearest:
        return
    n = await ctx.row(
        """
        SELECT p.name, ST_Distance(p.geom::geography, site.g::geography) AS d
        FROM pois p, site WHERE p.category = ANY(:cats)
        ORDER BY p.geom <-> site.g LIMIT 1
        """,
        cats=categories,
    )
    if n:
        ctx.add(f"{key}.nearest_name", f"Nearest of: {label.lower()}", n.name, SOURCE_OSM)
        ctx.add(
            f"{key}.nearest_m", f"Distance to nearest of: {label.lower()}", n.d, SOURCE_OSM, "m"
        )


async def population(ctx: Context) -> None:
    """Census values for the impact area, weighting each area by how much of it overlaps."""
    r = await ctx.row(
        """
        , w AS (
            SELECT c.*, c.population * ST_Area(ST_Intersection(c.geom, site.ring)::geography)
                        / NULLIF(ST_Area(c.geom::geography), 0) AS people
            FROM census_areas c, site WHERE ST_Intersects(c.geom, site.ring)
        )
        SELECT sum(people) AS people,
               sum(people * pct_renters) / NULLIF(sum(people), 0) AS renters,
               sum(people * pct_transit) / NULLIF(sum(people), 0) AS transit,
               sum(people * median_age) / NULLIF(sum(people), 0) AS age,
               sum(people * avg_household) / NULLIF(sum(people), 0) AS household,
               (SELECT ST_Area(ST_Intersection(site.ring, ST_Union(n.geom))::geography)
                       / ST_Area(site.ring::geography)
                FROM neighbourhoods n, site GROUP BY site.ring) AS coverage
        FROM w
        """
    )
    if not r or r.people is None:
        return
    within = f"within {ctx.radius:g} m"
    ctx.values["population"] = r.people
    ctx.values["household"] = r.household
    ctx.add(
        "population.residents",
        f"Residents {within}",
        round(r.people, -1),
        SOURCE_CENSUS,
        "residents",
    )
    if r.renters is not None:
        ctx.add(
            "population.renters_pct",
            f"Households renting {within}",
            r.renters * 100,
            SOURCE_CENSUS,
            "%",
            f"{r.renters * 100:.0f}%",
        )
    if r.transit is not None:
        ctx.add(
            "population.transit_commute_pct",
            f"Commuters taking transit {within} (May 2021, during COVID-19)",
            r.transit * 100,
            SOURCE_CENSUS,
            "%",
            f"{r.transit * 100:.0f}%",
        )
    if r.age is not None:
        ctx.add("population.median_age", f"Median age {within}", r.age, SOURCE_CENSUS, "years")
    if r.coverage is not None and r.coverage < 0.98:
        ctx.add(
            "population.coverage_pct",
            "Share of the impact area with census data loaded",
            r.coverage * 100,
            SOURCE_CENSUS,
            "%",
            f"{r.coverage * 100:.0f}% (figures for the impact area are partial)",
        )


async def homes_added(ctx: Context) -> None:
    units = ctx.proposal.params.get("units")
    if units is None:
        return
    ctx.add("proposal.homes", "New homes", units, SOURCE_PROPOSAL, "homes")
    household = ctx.values.get("household")
    if household:
        people = round(units * household, -1)
        ctx.values["new_residents"] = people
        ctx.add(
            "proposal.new_residents",
            "Estimated new residents (homes × local average household size)",
            people,
            f"{SOURCE_PROPOSAL} + {SOURCE_CENSUS}",
            "residents",
        )
        ctx.add(
            "population.avg_household",
            f"Average household size within {ctx.radius:g} m",
            round(household, 2),
            SOURCE_CENSUS,
            "people",
        )
        if ctx.values.get("population"):
            pct = people / ctx.values["population"] * 100
            ctx.add(
                "proposal.population_increase_pct",
                f"Increase in residents within {ctx.radius:g} m",
                pct,
                f"{SOURCE_PROPOSAL} + {SOURCE_CENSUS}",
                "%",
                f"{pct:.0f}%",
            )


async def floor_area(ctx: Context) -> None:
    storeys = ctx.values.get("storeys")
    if storeys:
        area = ctx.values["site_area"] * storeys
        ctx.add(
            "proposal.floor_area_m2",
            "Gross floor area (site area × storeys)",
            round(area, -2),
            SOURCE_PROPOSAL,
            "m²",
        )


async def green_space_per_resident(ctx: Context) -> None:
    people = ctx.values.get("population")
    park_area = ctx.values.get("park_area")
    if not people or park_area is None:
        return
    within = f"within {ctx.radius:g} m"
    now = park_area / people
    ctx.add(
        "green.per_resident_m2",
        f"Park area per resident {within}",
        now,
        f"{SOURCE_PARKS} + {SOURCE_CENSUS}",
        "m²",
    )
    after = None
    if ctx.typedef.type == "park":
        after = (park_area + ctx.values["site_area"]) / people
    elif ctx.values.get("new_residents"):
        after = park_area / (people + ctx.values["new_residents"])
    if after is not None:
        ctx.add(
            "green.per_resident_after_m2",
            f"Park area per resident {within} after this proposal",
            after,
            f"{SOURCE_PARKS} + {SOURCE_CENSUS}",
            "m²",
        )


def _station(name: str) -> str:
    """'Union Station - Northbound Platform' -> 'Union Station'."""
    return name.split(" - ")[0]


METRICS: dict[str, Callable[[Context], Awaitable[None]]] = {
    "replaced": replaced,
    "site": site,
    "zoning_fit": zoning_fit,
    "height_context": height_context,
    "transit": transit,
    "parks": parks,
    "schools": schools,
    "groceries": groceries,
    "retail_nearby": retail_nearby,
    "population": population,
    "homes_added": homes_added,
    "floor_area": floor_area,
    "green_space_per_resident": green_space_per_resident,
}


async def build_fact_sheet(
    conn: AsyncConnection, proposal: ProposalInput, typedef: TypeDef
) -> FactSheet:
    ctx = Context(conn, proposal, typedef)
    needed = list(typedef.impact_metrics)
    # Green space per resident builds on parks and population.
    if "green_space_per_resident" in needed and "parks" not in needed:
        needed.insert(needed.index("green_space_per_resident"), "parks")
    for name in needed:
        await METRICS[name](ctx)
    names = {f.id: f.display for f in ctx.facts}
    site_name = names.get("replaced.name") or names.get("site.neighbourhood") or "Selected site"
    return FactSheet(
        type=typedef.type,
        type_label=typedef.label,
        params=proposal.params,
        impact_radius_m=typedef.impact_radius_m,
        site_name=site_name,
        facts=ctx.facts,
    )
