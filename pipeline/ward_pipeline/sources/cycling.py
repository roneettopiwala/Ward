"""The City's cycling network, citywide, grouped into four facility types."""

import logging

import geopandas as gpd
import shapely
from sqlalchemy import Engine

from ..cache import toronto_resource
from ..db import upsert

log = logging.getLogger(__name__)


def facility_type(infra: str | None) -> str | None:
    """painted, protected, trail or shared, from the City's infrastructure label."""
    if not infra:
        return None
    if infra.startswith("Bike Lane"):
        return "painted"
    if "Cycle Track" in infra:
        return "protected"
    if infra.startswith("Multi-Use Trail") or infra == "Park Road":
        return "trail"
    if infra.startswith(("Sharrows", "Signed Route")):
        return "shared"
    return None


def load() -> gpd.GeoDataFrame:
    path = toronto_resource("cycling-network", "cycling-network - 4326.gpkg", "cycling.gpkg")
    raw = gpd.read_file(path, columns=["SEGMENT_ID", "STREET_NAME", "INFRA_HIGHORDER", "INSTALLED"])
    gdf = gpd.GeoDataFrame(
        {
            "fid": "cycling:" + raw["SEGMENT_ID"].astype("int64").astype(str),
            "name": raw["STREET_NAME"],
            "facility_type": raw["INFRA_HIGHORDER"].map(facility_type),
            "installed": raw["INSTALLED"].astype("Int64"),
        },
        geometry=shapely.force_2d(raw.geometry.values),
        crs=raw.crs,
    )
    gdf = gdf.dropna(subset=["facility_type"])
    log.info("cycling: %d segments", len(gdf))
    return gdf


def ingest(eng: Engine) -> int:
    return upsert(eng, load(), "cycling", "fid")
