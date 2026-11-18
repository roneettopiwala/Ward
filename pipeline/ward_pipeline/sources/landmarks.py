"""Landmarks: notable named places from OpenStreetMap, with facts from Wikidata.

A feature counts as notable when OSM links it to Wikidata or tags a capacity,
a heritage status or a historic kind. Wikidata adds a short description, the
opening year and capacity, and heritage designations, fetched once through its
public API (batched, cached in .cache/wikidata/).

Wikimedia's robot policy asks automated clients to give a contact in their
User-Agent, so the Wikidata step runs only when WIKIDATA_CONTACT (a URL or
email) is set in pipeline/.env; without it landmarks keep their OSM facts only.

Only features inside the City of Toronto are kept.
"""

import json
import logging
import os
import re
import time
from hashlib import sha256

import geopandas as gpd
import httpx
import pandas as pd
from sqlalchemy import Engine, text

from ..cache import cached
from ..config import CACHE_DIR, WGS84
from ..db import upsert
from .osm import _OTHER_TAG, EXTRACT, EXTRACT_URL, POI_KEYS, _category

log = logging.getLogger(__name__)

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "Ward-research/0.1 (non-commercial city planning simulator; {contact})"
WIKIDATA_CACHE = CACHE_DIR / "wikidata"
BATCH = 50
PAUSE_S = 1.0

TAGS = [
    "name", "wikidata", "capacity", "start_date", "heritage", "historic", "boundary", "place",
    "building", *POI_KEYS,
]  # fmt: skip
NOTABLE = (
    "other_tags LIKE '%\"wikidata\"=>%' OR other_tags LIKE '%\"capacity\"=>%' "
    "OR other_tags LIKE '%\"heritage\"=>%' OR other_tags LIKE '%\"historic\"=>%'"
)
QID = re.compile(r"^Q\d+$")
# Wikidata properties: inception, date of official opening, maximum capacity,
# heritage designation.
INCEPTION, OPENED, CAPACITY, HERITAGE = "P571", "P1619", "P1083", "P1435"


def _read(pbf: str, layer: str) -> gpd.GeoDataFrame:
    df = gpd.read_file(pbf, layer=layer, where=NOTABLE).to_crs(WGS84)
    tags = df["other_tags"].fillna("").map(lambda s: dict(_OTHER_TAG.findall(s)))
    for key in TAGS:
        from_tags = tags.map(lambda t, k=key: t.get(k))
        df[key] = df[key].fillna(from_tags) if key in df.columns else from_tags
    if layer == "multipolygons":
        way = df["osm_way_id"].notna()
        df["osm_id"] = ("w" + df["osm_way_id"].astype("string")).where(
            way, "r" + df["osm_id"].astype("string")
        )
    else:
        df["osm_id"] = "n" + df["osm_id"].astype("string")
    return df[df["name"].notna()]


def _int(v: object) -> int | None:
    m = re.match(r"\s*(\d[\d,]*)", str(v)) if v is not None and not pd.isna(v) else None
    return int(m.group(1).replace(",", "")) if m else None


def load_osm() -> gpd.GeoDataFrame:
    pbf = str(cached(EXTRACT, EXTRACT_URL))
    parts = [_read(pbf, "points"), _read(pbf, "multipolygons")]
    df = pd.concat(parts, ignore_index=True)
    df["kind"] = _category(df)
    # Boundaries and named areas (the city, wards, neighbourhoods) aren't places;
    # a feature must be a kind of place, a building, or tagged heritage, historic
    # or with a capacity.
    area = df["boundary"].notna() | df["place"].notna()
    placelike = df[["kind", "building", "historic", "heritage", "capacity"]].notna().any(axis=1)
    df = df[~area & placelike]
    wikidata = df["wikidata"].where(df["wikidata"].fillna("").str.match(QID.pattern))
    gdf = gpd.GeoDataFrame(
        {
            "fid": "osm:" + df["osm_id"],
            "name": df["name"],
            "kind": df["kind"].fillna(df["historic"]),
            "wikidata": wikidata,
            "osm_capacity": df["capacity"].map(_int).astype("Int64"),
            "osm_opened": df["start_date"],
            "osm_heritage": df["heritage"],
        },
        geometry=df.geometry,
        crs=WGS84,
    ).drop_duplicates("fid")
    log.info("landmarks: %d notable OSM features", len(gdf))
    return gdf


def _get(params: dict[str, str]) -> dict:
    """One Wikidata API call, cached on disk."""
    key = sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:24]
    path = WIKIDATA_CACHE / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    WIKIDATA_CACHE.mkdir(parents=True, exist_ok=True)
    time.sleep(PAUSE_S)
    r = httpx.get(
        WIKIDATA_API,
        params={**params, "format": "json"},
        headers={"User-Agent": USER_AGENT.format(contact=os.environ["WIKIDATA_CONTACT"])},
        timeout=60,
    )
    r.raise_for_status()
    path.write_text(r.text)
    return r.json()


def _values(claims: dict, prop: str) -> list:
    return [
        c["mainsnak"]["datavalue"]["value"]
        for c in claims.get(prop, [])
        if c.get("mainsnak", {}).get("snaktype") == "value"
    ]


def _year(values: list) -> int | None:
    years = [int(v["time"][1:5]) for v in values if isinstance(v, dict) and "time" in v]
    return min(years) if years else None


def wikidata_facts(ids: list[str]) -> dict[str, dict]:
    entities: dict[str, dict] = {}
    for i in range(0, len(ids), BATCH):
        batch = "|".join(ids[i : i + BATCH])
        got = _get({"action": "wbgetentities", "ids": batch, "props": "claims|descriptions",
                    "languages": "en"})  # fmt: skip
        entities.update(got.get("entities", {}))
    designations = sorted(
        {v["id"] for e in entities.values() for v in _values(e.get("claims", {}), HERITAGE)}
    )
    labels: dict[str, str] = {}
    for i in range(0, len(designations), BATCH):
        got = _get({"action": "wbgetentities", "ids": "|".join(designations[i : i + BATCH]),
                    "props": "labels", "languages": "en"})  # fmt: skip
        for qid, e in got.get("entities", {}).items():
            if label := e.get("labels", {}).get("en", {}).get("value"):
                labels[qid] = label
    out = {}
    for qid, e in entities.items():
        claims = e.get("claims", {})
        capacity = [_int(v.get("amount")) for v in _values(claims, CAPACITY)]
        out[qid] = {
            "wd_description": e.get("descriptions", {}).get("en", {}).get("value"),
            "wd_opened": _year(_values(claims, OPENED)) or _year(_values(claims, INCEPTION)),
            "wd_capacity": max((c for c in capacity if c), default=None),
            "wd_heritage": [labels[v["id"]] for v in _values(claims, HERITAGE) if v["id"] in labels]
            or None,
        }
    return out


def ingest(eng: Engine) -> int:
    gdf = load_osm()
    ids = sorted(set(gdf["wikidata"].dropna()))
    if os.environ.get("WIKIDATA_CONTACT"):
        log.info("landmarks: fetching %d Wikidata entities", len(ids))
        facts = wikidata_facts(ids)
    else:
        log.warning("landmarks: WIKIDATA_CONTACT not set; skipping Wikidata facts")
        facts = {}
    for col in ("wd_description", "wd_opened", "wd_capacity", "wd_heritage"):
        gdf[col] = gdf["wikidata"].map(lambda q, c=col: facts.get(q, {}).get(c) if q else None)
    gdf["wd_opened"] = gdf["wd_opened"].astype("Int64")
    gdf["wd_capacity"] = gdf["wd_capacity"].astype("Int64")
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM landmarks"))
    n = upsert(eng, gdf, "landmarks", "fid")
    with eng.begin() as conn:
        outside = conn.execute(
            text(
                "DELETE FROM landmarks l WHERE NOT EXISTS ("
                "SELECT 1 FROM neighbourhoods nb WHERE ST_Intersects(nb.geom, l.geom))"
            )
        ).rowcount
    log.info("landmarks: %d outside the city dropped", outside)
    return n - outside
