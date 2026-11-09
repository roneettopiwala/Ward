"""Buildings from the City's 3D massing, with use and a name joined in.

Massing has heights but no ids, uses or names, so:
- fid: a hash of the footprint, stable while the footprint is unchanged
- use: the OSM building it overlaps most, else its zoning class
- name: OSM building name, else a named place inside it, else its address,
  else a generated description ("3-storey residential building")
"""

import hashlib
import logging

import geopandas as gpd
import pandas as pd
import shapely
from sqlalchemy import Engine

from ..area import Area, as_multipolygon
from ..cache import toronto_resource
from ..config import METRIC_CRS, WGS84
from ..db import upsert
from .osm import OsmData

log = logging.getLogger(__name__)

STOREY_M = 3.5
# Share of a massing footprint an OSM building must cover to lend its tags.
MIN_OSM_OVERLAP = 0.3

USE_BY_BUILDING_TAG = {
    "residential": [
        "apartments",
        "residential",
        "house",
        "detached",
        "semidetached_house",
        "terrace",
        "dormitory",
        "bungalow",
        "townhouse",
    ],
    "commercial": ["commercial", "retail", "supermarket", "kiosk", "hotel", "mall"],
    "office": ["office"],
    "industrial": ["industrial", "warehouse", "manufacture"],
    "institutional": [
        "school",
        "university",
        "college",
        "kindergarten",
        "hospital",
        "civic",
        "public",
        "government",
        "fire_station",
        "police",
    ],
    "religious": ["church", "mosque", "synagogue", "temple", "cathedral", "chapel", "religious"],
    "recreation": ["stadium", "grandstand", "sports_centre", "sports_hall", "pavilion"],
    "transportation": ["train_station", "transportation"],
    "parking": ["parking", "garage", "garages", "carport"],
    "utility": ["service", "transformer_tower"],
}
USE_BY_TAG = {tag: use for use, tags in USE_BY_BUILDING_TAG.items() for tag in tags}
USE_BY_ZONE_CLASS = {
    "residential": "residential",
    "residential apartment": "residential",
    "commercial residential": "mixed",
    "commercial residential employment": "mixed",
    "commercial local": "commercial",
    "employment industrial": "industrial",
    "institutional": "institutional",
    "open space": "recreation",
    "utility and transportation": "utility",
}


def load(
    area: Area,
    osm: OsmData,
    addresses: gpd.GeoDataFrame,
    parcels: gpd.GeoDataFrame,
    zones: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    gdf = _massing(area)
    gdf["fid"] = gdf.geometry.map(_fid)
    gdf = gdf.drop_duplicates("fid").reset_index(drop=True)

    tags = _osm_match(gdf, osm.buildings)
    points = gdf.set_geometry(gdf.representative_point())
    zone_class = _first_within(points, zones, "zone_class")
    gdf["use"] = [
        (_use(t) if t else None) or USE_BY_ZONE_CLASS.get(z)
        for t, z in zip(tags, zone_class, strict=True)
    ]
    poi_counts = osm.pois.sjoin(gdf[["geometry"]], predicate="within").groupby("index_right").size()
    has_pois = gdf.index.to_series().map(poi_counts).fillna(0) > 0
    gdf.loc[(gdf["use"] == "residential") & has_pois, "use"] = "mixed"

    gdf["name"] = [
        _name(i, t, gdf, osm, addresses, parcels, points)
        for i, t in zip(gdf.index, tags, strict=True)
    ]
    log.info("buildings: %d", len(gdf))
    return gdf[["fid", "height_m", "use", "name", "geometry"]]


def ingest(eng: Engine, buildings: gpd.GeoDataFrame) -> int:
    return upsert(eng, buildings, "buildings", "fid")


def _massing(area: Area) -> gpd.GeoDataFrame:
    path = toronto_resource("3d-massing", "3DMassingShapefile_2025_WGS84.zip", "massing-2025.zip")
    # Despite the file name, the data is in Web Mercator.
    bbox = gpd.GeoSeries([area.geom], crs=WGS84).to_crs(3857).total_bounds
    raw = gpd.read_file(f"/vsizip/{path}", columns=["MAX_HEIGHT", "AVG_HEIGHT"], bbox=tuple(bbox))
    raw = raw.to_crs(WGS84)
    raw = raw[raw.representative_point().within(area.geom)]
    # Site-plan entries have MAX_HEIGHT 0 and the real height in AVG_HEIGHT.
    height = raw["MAX_HEIGHT"].where(raw["MAX_HEIGHT"] > 0, raw["AVG_HEIGHT"])
    geom = shapely.force_2d(raw.geometry.values).copy()
    gdf = gpd.GeoDataFrame(
        {"height_m": height.where(height > 0).round(1).values},
        geometry=[as_multipolygon(shapely.make_valid(g)) for g in geom],
        crs=WGS84,
    )
    return gdf[gdf.geom_type == "MultiPolygon"]


def _fid(geom: shapely.Geometry) -> str:
    wkb = shapely.to_wkb(shapely.set_precision(geom, 1e-7), output_dimension=2)
    return "building:" + hashlib.sha1(wkb).hexdigest()[:12]


def _osm_match(gdf: gpd.GeoDataFrame, osm_buildings: gpd.GeoDataFrame) -> list[dict | None]:
    """The tags of the OSM building covering the largest share of each footprint."""
    if osm_buildings.empty:
        return [None] * len(gdf)
    a = gdf[["geometry"]].to_crs(METRIC_CRS).reset_index(names="bid")
    b = osm_buildings.to_crs(METRIC_CRS).reset_index(names="oid")
    pieces = a.overlay(b[["oid", "geometry"]], how="intersection", keep_geom_type=True)
    pieces["share"] = pieces.area / pieces["bid"].map(a.set_index("bid").area)
    best = pieces[pieces["share"] >= MIN_OSM_OVERLAP].sort_values("share")
    best = best.drop_duplicates("bid", keep="last").set_index("bid")["oid"]
    # Missing tags come through as NaN, which is truthy; make them None.
    attrs = osm_buildings.drop(columns="geometry").astype(object)
    records = attrs.where(attrs.notna(), None).to_dict("records")
    return [records[best[i]] if i in best.index else None for i in gdf.index]


def _use(tags: dict) -> str | None:
    by_tag = USE_BY_TAG.get(tags.get("building") or "")
    if by_tag:
        return by_tag
    if tags.get("leisure"):
        return "recreation"
    if tags.get("amenity") in USE_BY_TAG:
        return USE_BY_TAG[tags["amenity"]]
    if tags.get("office"):
        return "office"
    if tags.get("shop") or tags.get("tourism") == "hotel":
        return "commercial"
    return None


def _first_within(points: gpd.GeoDataFrame, polys: gpd.GeoDataFrame, col: str) -> pd.Series:
    if polys.empty:
        return pd.Series([None] * len(points), index=points.index)
    hits = points[["geometry"]].sjoin(polys[[col, "geometry"]], predicate="within")
    return points.index.to_series().map(hits[~hits.index.duplicated()][col])


def _name(
    i: int,
    tags: dict | None,
    gdf: gpd.GeoDataFrame,
    osm: OsmData,
    addresses: gpd.GeoDataFrame,
    parcels: gpd.GeoDataFrame,
    points: gpd.GeoDataFrame,
) -> str:
    footprint = gdf.geometry[i]
    named = (tags or {}).get("name") or _named_inside(footprint, osm, addresses)
    if named:
        return named
    inside = addresses[addresses.within(footprint)]
    if not inside.empty:
        return inside["address"].iloc[0]
    parcel = parcels[parcels.contains(points.geometry[i])]
    if not parcel.empty and isinstance(parcel["address"].iloc[0], str):
        return parcel["address"].iloc[0]
    return _describe(gdf["height_m"][i], gdf["use"][i])


def _named_inside(
    footprint: shapely.Geometry, osm: OsmData, addresses: gpd.GeoDataFrame
) -> str | None:
    """A place name for the building: an address place name, or its only named POI."""
    places = addresses[addresses["place_name"].notna() & addresses.within(footprint)]
    if not places.empty:
        return places["place_name"].iloc[0]
    pois = osm.pois[osm.pois.within(footprint)]
    return pois["name"].iloc[0] if len(pois) == 1 else None


def _describe(height_m: float | None, use: str | None) -> str:
    kind = f"{use} building" if isinstance(use, str) else "building"
    if height_m is None or pd.isna(height_m):
        return kind.capitalize()
    storeys = max(1, round(height_m / STOREY_M))
    return f"{storeys}-storey {kind}"
