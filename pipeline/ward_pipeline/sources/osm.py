"""OpenStreetMap via Overpass: named POIs, plus building tags for use and names."""

import json
import logging
from dataclasses import dataclass

import geopandas as gpd
import httpx
from shapely import LineString, Point, Polygon, get_parts, polygonize, unary_union
from shapely.geometry.base import BaseGeometry
from sqlalchemy import Engine

from ..area import Area
from ..config import CACHE_DIR, WGS84
from ..db import upsert

log = logging.getLogger(__name__)

OVERPASS = "https://overpass-api.de/api/interpreter"
POI_KEYS = ["amenity", "shop", "tourism", "leisure", "office", "healthcare", "craft", "historic"]
# OSM values we rename to Ward's category vocabulary.
CATEGORY_ALIASES = {"supermarket": "grocery", "greengrocer": "grocery", "doctors": "clinic"}


@dataclass(frozen=True)
class OsmData:
    pois: gpd.GeoDataFrame  # fid, category, name, geometry (points)
    buildings: gpd.GeoDataFrame  # building, name, tags..., geometry (polygons)


def fetch(area: Area, cache_key: str) -> OsmData:
    elements = _query(area, cache_key)
    pois, buildings = [], []
    for el in elements:
        tags = el.get("tags", {})
        geom = _geometry(el)
        if geom is None:
            continue
        if "building" in tags and geom.geom_type in ("Polygon", "MultiPolygon"):
            buildings.append({"osm_id": _osm_id(el), "geometry": geom, **_building_tags(tags)})
        category = next((tags[k] for k in POI_KEYS if k in tags), None)
        if tags.get("name") and category:
            point = geom if isinstance(geom, Point) else geom.representative_point()
            pois.append(
                {
                    "fid": f"poi:{_osm_id(el)}",
                    "category": CATEGORY_ALIASES.get(category, category),
                    "name": tags["name"],
                    "geometry": point,
                }
            )
    poi_gdf = gpd.GeoDataFrame(pois, geometry="geometry", crs=WGS84)
    poi_gdf = poi_gdf[poi_gdf.within(area.geom)].drop_duplicates("fid")
    bld_gdf = gpd.GeoDataFrame(buildings, geometry="geometry", crs=WGS84)
    log.info("osm: %d named POIs, %d buildings", len(poi_gdf), len(bld_gdf))
    return OsmData(poi_gdf, bld_gdf)


def ingest_pois(eng: Engine, osm: OsmData) -> int:
    return upsert(eng, osm.pois, "pois", "fid")


def _query(area: Area, cache_key: str) -> list[dict]:
    path = CACHE_DIR / f"osm-{cache_key}.json"
    if path.exists():
        return json.loads(path.read_text())
    w, s, e, n = area.bounds
    bbox = f"{s},{w},{n},{e}"
    poi_filters = "".join(f'nwr["name"]["{k}"]({bbox});' for k in POI_KEYS)
    q = (
        f'[out:json][timeout:180];({poi_filters}way["building"]({bbox});'
        f'relation["building"]({bbox}););out geom;'
    )
    log.info("querying overpass")
    r = httpx.post(
        OVERPASS,
        data={"data": q},
        timeout=240,
        headers={"User-Agent": "ward-pipeline (city planning research)"},
    )
    elements = r.raise_for_status().json()["elements"]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(elements))
    return elements


def _osm_id(el: dict) -> str:
    return f"{el['type'][0]}{el['id']}"  # n123, w456, r789


def _building_tags(tags: dict) -> dict:
    keep = ["building", "name", "amenity", "shop", "leisure", "tourism", "office"]
    return {k: tags.get(k) for k in keep}


def _geometry(el: dict) -> BaseGeometry | None:
    if el["type"] == "node":
        return Point(el["lon"], el["lat"])
    if el["type"] == "way":
        coords = [(p["lon"], p["lat"]) for p in el.get("geometry", [])]
        if len(coords) >= 4 and coords[0] == coords[-1]:
            return Polygon(coords)
        return LineString(coords) if len(coords) >= 2 else None
    # Relations: assemble outer rings from member ways.
    outers = [
        LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
        for m in el.get("members", [])
        if m.get("role") == "outer" and m.get("geometry") and len(m["geometry"]) >= 2
    ]
    polys = list(polygonize(get_parts(unary_union(outers))).geoms) if outers else []
    return unary_union(polys) if polys else None
