"""Toronto Centreline: the street network, citywide, as a pgRouting graph.

Each segment runs between two City intersection ids, which become the graph's
source and target nodes. Rivers, rail, hydro lines, shorelines and other
non-street lines are left out.
"""

import logging

import geopandas as gpd
import shapely
from sqlalchemy import Engine

from ..cache import toronto_resource
from ..config import METRIC_CRS
from ..db import upsert

log = logging.getLogger(__name__)

ROAD_CLASS = {
    "Expressway": "expressway",
    # Only expressway ramps are highway; the others are grade separations on
    # ordinary streets (e.g. Lawrence Ave E over Kennedy Rd).
    "Expressway Ramp": "ramp",
    "Major Arterial Ramp": "arterial_ramp",
    "Minor Arterial Ramp": "arterial_ramp",
    "Collector Ramp": "arterial_ramp",
    "Other Ramp": "arterial_ramp",
    "Major Arterial": "major_arterial",
    "Minor Arterial": "minor_arterial",
    "Collector": "collector",
    "Local": "local",
    "Laneway": "laneway",
    "Access Road": "access",
    "Busway": "busway",
    "Trail": "trail",
    "Walkway": "walkway",
}


def load() -> gpd.GeoDataFrame:
    path = toronto_resource(
        "toronto-centreline-tcl", "Centreline - Version 2 - 4326.gpkg", "centreline.gpkg"
    )
    raw = gpd.read_file(
        path,
        columns=[
            "CENTRELINE_ID",
            "LINEAR_NAME_FULL",
            "FEATURE_CODE_DESC",
            "FROM_INTERSECTION_ID",
            "TO_INTERSECTION_ID",
        ],
    )
    raw = raw[raw["FEATURE_CODE_DESC"].isin(ROAD_CLASS)]
    raw = raw.dropna(subset=["FROM_INTERSECTION_ID", "TO_INTERSECTION_ID"])
    # Every segment is a single line stored as a one-part MultiLineString.
    lines = shapely.line_merge(shapely.force_2d(raw.geometry.values))
    gdf = gpd.GeoDataFrame(
        {
            "fid": "street:" + raw["CENTRELINE_ID"].astype("int64").astype(str).values,
            "name": raw["LINEAR_NAME_FULL"].values,
            "road_class": raw["FEATURE_CODE_DESC"].map(ROAD_CLASS).values,
            "source": raw["FROM_INTERSECTION_ID"].astype("int64").values,
            "target": raw["TO_INTERSECTION_ID"].astype("int64").values,
        },
        geometry=lines,
        crs=raw.crs,
    )
    gdf = gdf[gdf.geom_type == "LineString"]
    gdf["length_m"] = gdf.geometry.to_crs(METRIC_CRS).length.round(1)
    log.info("streets: %d segments", len(gdf))
    return gdf


def ingest(eng: Engine) -> int:
    return upsert(eng, load(), "streets", "fid")
