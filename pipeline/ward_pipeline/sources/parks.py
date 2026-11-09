"""Public parks and open space from the City's Green Spaces dataset."""

import logging

import geopandas as gpd
import shapely
from sqlalchemy import Engine

from ..area import Area, as_multipolygon
from ..cache import toronto_resource
from ..config import METRIC_CRS, WGS84
from ..db import upsert

log = logging.getLogger(__name__)

# Publicly usable green space. Leaves out traffic islands, boulevards, hydro
# corridors, cemeteries, golf courses and other land the public can't use as a park.
PARK_CLASSES = ["Park", "Open Green Space", "Civic Centre Square"]
# Parks this far outside the area still count for metrics near its edge.
CONTEXT_M = 1000


def load(area: Area) -> gpd.GeoDataFrame:
    path = toronto_resource("green-spaces", "Green Spaces - 4326.gpkg", "green-spaces.gpkg")
    context = area.buffered(CONTEXT_M)
    raw = gpd.read_file(
        path, columns=["AREA_ID", "AREA_CLASS", "AREA_NAME"], bbox=tuple(context.bounds)
    ).to_crs(WGS84)
    raw = raw[raw["AREA_CLASS"].isin(PARK_CLASSES) & raw.intersects(context)]
    gdf = gpd.GeoDataFrame(
        {
            "fid": "park:" + raw["AREA_ID"].astype(int).astype(str),
            "name": raw["AREA_NAME"].str.title(),
            "area_m2": raw.geometry.to_crs(METRIC_CRS).area.round(1),
        },
        geometry=[as_multipolygon(shapely.make_valid(g)) for g in raw.geometry],
        crs=WGS84,
    )
    gdf = gdf[gdf.geom_type == "MultiPolygon"]
    log.info("parks: %d", len(gdf))
    return gdf


def ingest(eng: Engine, area: Area) -> int:
    return upsert(eng, load(area), "parks", "fid")
