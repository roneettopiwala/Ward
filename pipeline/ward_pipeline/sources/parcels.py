"""Toronto property boundaries, with an address from the address points."""

import logging
import re

import geopandas as gpd
from sqlalchemy import Engine

from ..area import Area, as_multipolygon
from ..cache import toronto_resource
from ..config import METRIC_CRS
from ..db import upsert

log = logging.getLogger(__name__)

STATED_AREA = re.compile(r"([\d.]+)\s*sq\.?\s*m", re.I)


def load(area: Area, addresses: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    path = toronto_resource(
        "property-boundaries", "Property Boundaries - 4326.gpkg", "parcels.gpkg"
    )
    raw = gpd.read_file(path, columns=["PARCELID", "STATEDAREA"], mask=area.geom)
    raw = raw[raw.representative_point().within(area.geom)]
    measured = raw.to_crs(METRIC_CRS).area
    stated = raw["STATEDAREA"].str.extract(STATED_AREA, expand=False).astype(float)
    gdf = raw.assign(
        fid="parcel:" + raw["PARCELID"].astype(str),
        area_m2=stated.fillna(measured).round(1),
    )
    first_address = (
        addresses[["address", "geometry"]]
        .sjoin(gdf[["fid", "geometry"]], predicate="within")
        .drop_duplicates("fid")  # addresses arrive best-first
        .set_index("fid")["address"]
    )
    gdf["address"] = gdf["fid"].map(first_address)
    gdf = gdf.set_geometry(gdf.geometry.apply(as_multipolygon))
    log.info("parcels: %d", len(gdf))
    return gdf[["fid", "address", "area_m2", "geometry"]].drop_duplicates("fid")


def ingest(eng: Engine, parcels: gpd.GeoDataFrame) -> int:
    return upsert(eng, parcels, "parcels", "fid")
