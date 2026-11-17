"""OpenStreetMap from a local Toronto extract: named POIs, plus building tags for use and names.

The extract (BBBike's Toronto cut of OpenStreetMap, about 100 MB) is downloaded
once and converted once into a small GeoPackage holding just the buildings and
named POIs, with a spatial index. Each area then reads its part of that.
"""

import logging
import re
from dataclasses import dataclass

import geopandas as gpd
import pandas as pd
import pyogrio
from sqlalchemy import Engine

from ..area import Area
from ..cache import cached
from ..config import CACHE_DIR, WGS84
from ..db import upsert

log = logging.getLogger(__name__)

EXTRACT_URL = "https://download.bbbike.org/osm/bbbike/Toronto/Toronto.osm.pbf"
EXTRACT = "toronto.osm.pbf"
PREPARED = CACHE_DIR / "osm-toronto.gpkg"

POI_KEYS = ["amenity", "shop", "tourism", "leisure", "office", "healthcare", "craft", "historic"]
BUILDING_TAGS = ["building", "name", "amenity", "shop", "leisure", "tourism", "office"]
# OSM values we rename to Ward's category vocabulary.
CATEGORY_ALIASES = {"supermarket": "grocery", "greengrocer": "grocery", "doctors": "clinic"}

# GDAL's OSM driver puts tags without their own column into other_tags: "k"=>"v",...
_OTHER_TAG = re.compile(r'"((?:[^"\\]|\\.)*)"=>"((?:[^"\\]|\\.)*)"')


@dataclass(frozen=True)
class OsmData:
    pois: gpd.GeoDataFrame  # fid, category, name, geometry (points)
    buildings: gpd.GeoDataFrame  # osm_id, building, name, tags..., geometry (polygons)


def fetch(area: Area, cache_key: str = "") -> OsmData:  # noqa: ARG001 (one extract for all areas)
    path = prepare()
    pois = gpd.read_file(path, layer="pois", mask=area.geom).rename(columns={"poi_fid": "fid"})
    buildings = gpd.read_file(path, layer="buildings", bbox=area.bounds)
    log.info("osm: %d named POIs, %d buildings", len(pois), len(buildings))
    return OsmData(pois.drop_duplicates("fid").reset_index(drop=True), buildings)


def ingest_pois(eng: Engine, osm: OsmData) -> int:
    return upsert(eng, osm.pois, "pois", "fid")


def prepare() -> str:
    """Convert the extract once into buildings and named POIs, spatially indexed."""
    if PREPARED.exists():
        return str(PREPARED)
    pbf = cached(EXTRACT, EXTRACT_URL)
    log.info("preparing OpenStreetMap buildings and POIs (once)")
    polys = _read(pbf, "multipolygons", [*BUILDING_TAGS, "craft", "historic"])
    points = _read(pbf, "points", ["name"])
    for df in (polys, points):
        df["category"] = _category(df)

    is_building = polys["building"].notna()
    buildings = polys.loc[is_building, ["osm_id", *BUILDING_TAGS, "geometry"]]

    named = pd.concat(
        [
            points[points["name"].notna() & points["category"].notna()],
            polys[polys["name"].notna() & polys["category"].notna()],
        ]
    )
    pois = gpd.GeoDataFrame(
        {
            # GeoPackage reserves "fid"; renamed back on read.
            "poi_fid": "poi:" + named["osm_id"],
            "category": named["category"].map(lambda c: CATEGORY_ALIASES.get(c, c)),
            "name": named["name"],
        },
        geometry=named.geometry.representative_point(),
        crs=WGS84,
    )

    tmp = PREPARED.with_suffix(".part.gpkg")
    tmp.unlink(missing_ok=True)
    pyogrio.write_dataframe(buildings, tmp, layer="buildings")
    pyogrio.write_dataframe(pois, tmp, layer="pois")
    tmp.rename(PREPARED)
    log.info("osm: prepared %d buildings and %d named POIs", len(buildings), len(pois))
    return str(PREPARED)


def _read(pbf: object, layer: str, columns: list[str]) -> gpd.GeoDataFrame:
    """One layer of the extract, with tags from other_tags spread into columns."""
    id_cols = ["osm_id", "osm_way_id"] if layer == "multipolygons" else ["osm_id"]
    available = set(pyogrio.read_info(pbf, layer=layer)["fields"])
    cols = [c for c in [*id_cols, *columns, "other_tags"] if c in available]
    df = gpd.read_file(pbf, layer=layer, columns=cols).to_crs(WGS84)
    tags = df["other_tags"].fillna("").map(lambda s: dict(_OTHER_TAG.findall(s)))
    for key in {*columns, *POI_KEYS}:
        from_tags = tags.map(lambda t, k=key: t.get(k))
        df[key] = df[key].fillna(from_tags) if key in df.columns else from_tags
    # Our ids match Overpass's: n123 for nodes, w456 for ways, r789 for relations.
    if layer == "multipolygons":
        way = df["osm_way_id"].notna()
        df["osm_id"] = ("w" + df["osm_way_id"].astype("string")).where(
            way, "r" + df["osm_id"].astype("string")
        )
    else:
        df["osm_id"] = "n" + df["osm_id"].astype("string")
    return df.drop(columns=[c for c in ("osm_way_id", "other_tags") if c in df.columns])


def _category(df: pd.DataFrame) -> pd.Series:
    """The first POI key with a value, in POI_KEYS order."""
    out = pd.Series(None, index=df.index, dtype="object")
    for key in reversed(POI_KEYS):
        out = df[key].where(df[key].notna(), out)
    return out
