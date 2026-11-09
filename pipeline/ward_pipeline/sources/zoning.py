"""Zoning By-law 569-2013: zone areas, with the height overlay's limit in metres.

Parts of the city (e.g. the Railway Lands) are not under 569-2013 and have no
open zoning data; they simply get no zoning rows.
"""

import logging

import geopandas as gpd
from sqlalchemy import Engine

from ..area import Area, as_multipolygon
from ..cache import toronto_resource
from ..config import METRIC_CRS
from ..db import replace_in_area

log = logging.getLogger(__name__)

ZONE_CLASS = {
    0: "residential",
    101: "residential apartment",
    1: "open space",
    2: "utility and transportation",
    4: "employment industrial",
    5: "institutional",
    6: "commercial residential employment",
    201: "commercial local",
    202: "commercial residential",
}


def load(area: Area) -> gpd.GeoDataFrame:
    zones = gpd.read_file(
        toronto_resource("zoning-by-law", "Zoning Area - 4326.gpkg", "zoning-area.gpkg"),
        columns=["GEN_ZONE", "ZN_ZONE", "FSI_TOTAL"],
        mask=area.geom,
    )
    heights = gpd.read_file(
        toronto_resource(
            "zoning-by-law", "Zoning Height Overlay - 4326.gpkg", "zoning-height.gpkg"
        ),
        columns=["HT_LABEL"],
        mask=area.geom,
    )
    zones["max_height_m"] = _height_by_largest_overlap(zones, heights)
    gdf = zones.assign(
        zone_code=zones["ZN_ZONE"],
        zone_class=zones["GEN_ZONE"].astype(int).map(ZONE_CLASS),
        max_density=zones["FSI_TOTAL"].where(zones["FSI_TOTAL"] > 0),
    )
    gdf = gdf.set_geometry(gdf.geometry.apply(as_multipolygon))
    gdf = gdf[["zone_code", "zone_class", "max_height_m", "max_density", "geometry"]]
    log.info("zoning: %d zones", len(gdf))
    return gdf


def ingest(eng: Engine, area: Area, zones: gpd.GeoDataFrame) -> int:
    return replace_in_area(eng, zones, "zoning", area.geom.wkt)


def _height_by_largest_overlap(zones: gpd.GeoDataFrame, heights: gpd.GeoDataFrame):  # noqa: ANN202
    if heights.empty or zones.empty:
        return None
    z = zones.to_crs(METRIC_CRS).reset_index(names="zone")
    h = heights.to_crs(METRIC_CRS)
    pieces = z[["zone", "geometry"]].overlay(h[["HT_LABEL", "geometry"]], how="intersection")
    pieces["overlap"] = pieces.area
    best = pieces.sort_values("overlap").drop_duplicates("zone", keep="last").set_index("zone")
    return z["zone"].map(best["HT_LABEL"].astype(float)).values
