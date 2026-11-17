"""Development applications: every Community Planning application since 2008.

From Toronto Open Data. The dataset has one row per address, so applications
on several addresses are grouped into one row at the first address.
"""

import logging

import geopandas as gpd
import pandas as pd
from sqlalchemy import Engine, text

from ..cache import toronto_resource
from ..db import upsert

log = logging.getLogger(__name__)

# The dataset's X/Y are NAD27 MTM zone 10 (checked against our lot boundaries).
SOURCE_CRS = "EPSG:2019"


def _address(row: pd.Series) -> str:
    parts = [row.STREET_NUM, row.STREET_NAME, row.STREET_TYPE, row.STREET_DIRECTION]
    return " ".join(str(p).strip().title() for p in parts if pd.notna(p) and str(p).strip())


def load() -> gpd.GeoDataFrame:
    path = toronto_resource(
        "development-applications", "Development Applications.csv", "development_applications.csv"
    )
    raw = pd.read_csv(path, dtype=str)
    raw = raw.dropna(subset=["APPLICATION#", "X", "Y"])
    raw["address"] = raw.apply(_address, axis=1)
    raw["x"], raw["y"] = raw["X"].astype(float), raw["Y"].astype(float)
    first = raw.groupby("APPLICATION#", sort=False).first()
    centre = raw.groupby("APPLICATION#", sort=False)[["x", "y"]].mean()
    gdf = gpd.GeoDataFrame(
        {
            "application_number": first.index.str.strip(),
            "application_type": first["APPLICATION_TYPE"].values,
            "address": first["address"].values,
            "description": first["DESCRIPTION"].values,
            "status": first["STATUS"].values,
            "date_submitted": pd.to_datetime(
                first["DATE_SUBMITTED"], errors="coerce"
            ).dt.date.values,
        },
        geometry=gpd.points_from_xy(centre.loc[first.index, "x"], centre.loc[first.index, "y"]),
        crs=SOURCE_CRS,
    ).to_crs(4326)
    log.info("applications: %d", len(gdf))
    return gdf


def ingest(eng: Engine) -> int:
    n = upsert(eng, load(), "applications", "application_number")
    with eng.begin() as conn:
        conn.execute(
            text(
                "UPDATE applications a SET neighbourhood_id = nb.id FROM neighbourhoods nb "
                "WHERE ST_Contains(nb.geom, a.geom)"
            )
        )
    return n
