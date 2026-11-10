"""2021 Census at dissemination-area level, from Statistics Canada.

Boundaries come from StatCan's cartographic boundary map service and the
values from the Census Profile SDMX API. Only area-level aggregates are kept.
"""

import io
import json
import logging

import geopandas as gpd
import httpx
import pandas as pd
from sqlalchemy import Engine

from ..area import Area, as_multipolygon
from ..config import WGS84
from ..db import upsert

log = logging.getLogger(__name__)

DA_LAYER = (
    "https://geo.statcan.gc.ca/geo_wa/rest/services/2021/"
    "Cartographic_boundary_files/MapServer/12/query"
)
PROFILE = "https://api.statcan.gc.ca/census-recensement/profile/sdmx/rest/data/STC_CP,DF_DA"
BATCH = 25

# Census Profile characteristic ids (2021). Groups map our labels to ids.
POPULATION, MEDIAN_AGE, AVG_HOUSEHOLD = 1, 40, 56
TENURE_TOTAL, RENTERS = 1400, 1402
COMMUTE_TOTAL, TRANSIT = 2603, 2607
AGE = {
    "0-14": [9],
    "15-24": [14, 15],
    "25-44": [16, 17, 18, 19],
    "45-64": [20, 21, 22, 23],
    "65+": [24],
}
HOUSING_TOTAL = 41
HOUSING = {
    "single_detached": [42],
    "semi_detached": [43],
    "row_house": [44],
    "duplex": [45],
    "apartment_under_5_storeys": [46],
    "apartment_5_plus_storeys": [47],
    "other": [48, 49],
}
OCCUPATION_TOTAL = 2248
OCCUPATION = {
    "management": [2249],
    "business_finance_admin": [2250],
    "sciences": [2251],
    "health": [2252],
    "education_law_government": [2253],
    "arts_culture_sport": [2254],
    "sales_service": [2255],
    "trades_transport": [2256],
    "natural_resources": [2257],
    "manufacturing_utilities": [2258],
}
LANGUAGE_TOTAL = 721  # language spoken most often at home
LANGUAGE = {"english": [724], "french": [725], "non_official": [726]}
COMMUTE = {"car": [2604], "transit": [2607], "walk": [2608], "bike": [2609], "other": [2610]}
HOUSEHOLD_TOTAL = 50  # private households by size
HOUSEHOLD = {"1": [51], "2": [52], "3": [53], "4": [54], "5+": [55]}

ALL_IDS = sorted(
    {
        POPULATION,
        MEDIAN_AGE,
        AVG_HOUSEHOLD,
        TENURE_TOTAL,
        RENTERS,
        COMMUTE_TOTAL,
        TRANSIT,
        HOUSING_TOTAL,
        OCCUPATION_TOTAL,
        LANGUAGE_TOTAL,
        HOUSEHOLD_TOTAL,
    }
    | {
        i
        for g in (AGE, HOUSING, OCCUPATION, LANGUAGE, COMMUTE, HOUSEHOLD)
        for ids in g.values()
        for i in ids
    }
)


DIST_COLUMNS = (
    "age_dist",
    "housing_dist",
    "occupation_dist",
    "language_dist",
    "commute_dist",
    "household_dist",
)


def ingest(eng: Engine, area: Area) -> int:
    das = _boundaries(area)
    values = _profile(das["dguid"].tolist())
    rows = [_aggregate(values.get(dguid, {})) for dguid in das["dguid"]]
    gdf = gpd.GeoDataFrame(
        pd.concat([das.reset_index(drop=True), pd.DataFrame(rows)], axis=1),
        geometry="geometry",
        crs=WGS84,
    )
    gdf["level"] = "DA"
    for col in DIST_COLUMNS:
        gdf[col] = gdf[col].map(lambda d: json.dumps(d) if d is not None else None)
    return upsert(eng, gdf, "census_areas", "dguid")


def _boundaries(area: Area) -> gpd.GeoDataFrame:
    """DAs whose interior point falls inside the area, tagged with their neighbourhood."""
    w, s, e, n = area.bounds
    features, offset = [], 0
    while True:
        page = (
            httpx.get(
                DA_LAYER,
                timeout=120,
                params={
                    "geometry": f"{w},{s},{e},{n}",
                    "geometryType": "esriGeometryEnvelope",
                    "inSR": WGS84,
                    "spatialRel": "esriSpatialRelIntersects",
                    "outFields": "DGUID",
                    "outSR": WGS84,
                    "f": "geojson",
                    "resultOffset": offset,
                },
            )
            .raise_for_status()
            .json()
        )
        features += page["features"]
        if not page.get("properties", {}).get("exceededTransferLimit"):
            break
        offset = len(features)
    das = gpd.GeoDataFrame.from_features(features, crs=WGS84).rename(columns={"DGUID": "dguid"})
    points = das.set_geometry(das.representative_point())
    joined = points.sjoin(area.neighbourhoods[["id", "geometry"]], predicate="within")
    das = das.loc[joined.index].assign(neighbourhood_id=joined["id"].astype(int))
    das = das.set_geometry(das.geometry.apply(as_multipolygon))
    log.info("census: %d dissemination areas", len(das))
    return das[["dguid", "neighbourhood_id", "geometry"]]


def _profile(dguids: list[str]) -> dict[str, dict[int, float]]:
    """{dguid: {characteristic id: value}} for the characteristics we use."""
    out: dict[str, dict[int, float]] = {}
    chars = "+".join(map(str, ALL_IDS))
    for i in range(0, len(dguids), BATCH):
        key = f"A5.{'+'.join(dguids[i : i + BATCH])}.1.{chars}.1"
        r = httpx.get(
            f"{PROFILE}/{key}", timeout=120, headers={"Accept": "application/vnd.sdmx.data+csv"}
        )
        if r.text.startswith("NoRecordsFound"):
            continue
        df = pd.read_csv(
            io.StringIO(r.raise_for_status().text),
            usecols=["REF_AREA", "CHARACTERISTIC", "OBS_VALUE"],
        )
        for row in df.dropna(subset=["OBS_VALUE"]).itertuples():
            out.setdefault(row.REF_AREA, {})[int(row.CHARACTERISTIC)] = float(row.OBS_VALUE)
    return out


def _aggregate(v: dict[int, float]) -> dict:
    def share(part: int, total: int) -> float | None:
        return round(v[part] / v[total], 4) if v.get(total) and part in v else None

    def dist(groups: dict[str, list[int]], total: int | None = None) -> dict | None:
        counts = {k: sum(v.get(i, 0.0) for i in ids) for k, ids in groups.items()}
        denom = v.get(total) if total else sum(counts.values())
        if not denom:
            return None
        shares = {k: round(c / denom, 4) for k, c in counts.items()}
        if total == LANGUAGE_TOTAL:
            shares["multiple"] = round(max(0.0, 1 - sum(shares.values())), 4)
        return shares

    pop = v.get(POPULATION)
    return {
        "population": int(pop) if pop is not None else None,
        "median_age": v.get(MEDIAN_AGE),
        "pct_renters": share(RENTERS, TENURE_TOTAL),
        "pct_transit": share(TRANSIT, COMMUTE_TOTAL),
        "avg_household": v.get(AVG_HOUSEHOLD),
        "age_dist": dist(AGE),
        "housing_dist": dist(HOUSING, HOUSING_TOTAL),
        "occupation_dist": dist(OCCUPATION, OCCUPATION_TOTAL),
        "language_dist": dist(LANGUAGE, LANGUAGE_TOTAL),
        "commute_dist": dist(COMMUTE, COMMUTE_TOTAL),
        "household_dist": dist(HOUSEHOLD, HOUSEHOLD_TOTAL),
    }
