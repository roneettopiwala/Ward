"""Toronto Heritage Register: listed and designated heritage properties.

Address points from Toronto Open Data. Status is 'Part IV' (individually
designated under the Ontario Heritage Act), 'Part V' (in a Heritage
Conservation District) or 'Listed' (on the register, not designated).
Demolished properties are left out.
"""

import logging

import geopandas as gpd
import pandas as pd
from sqlalchemy import Engine, text

from ..cache import toronto_resource
from ..db import upsert

log = logging.getLogger(__name__)


def _text(v: object) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = " ".join(str(v).split())
    return s or None


def load() -> gpd.GeoDataFrame:
    path = toronto_resource("heritage-register", "Heritage Register Data", "heritage_register.zip")
    raw = gpd.read_file(path).to_crs(4326)
    raw = raw[raw["YEAR_DEMOL"].isna() & raw.geometry.notna()]
    gdf = gpd.GeoDataFrame(
        {
            "id": raw["OBJECTID"].astype(int),
            "address": raw["ADDRESS"].map(_text),
            "status": raw["STATUS"].map(_text),
            "district": raw["HTG_CONSER"].map(_text),
            "built": raw["CONSTRUCTI"].map(_text),
            "architect": raw["ARCHITECT_"].map(_text),
            "description": raw["DESCRIPTIO"].map(_text),
        },
        geometry=raw.geometry,
        crs=4326,
    )
    log.info("heritage register: %d properties", len(gdf))
    return gdf


def ingest(eng: Engine) -> int:
    gdf = load()
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM heritage_properties"))
    return upsert(eng, gdf, "heritage_properties", "id")
