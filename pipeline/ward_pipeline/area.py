"""The area an ingest run covers: one or more City of Toronto neighbourhoods."""

from dataclasses import dataclass

import geopandas as gpd
from shapely import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from .cache import toronto_resource
from .config import METRIC_CRS, WGS84


@dataclass(frozen=True)
class Area:
    neighbourhoods: gpd.GeoDataFrame  # id, name, geometry (WGS84)
    geom: BaseGeometry  # union of the neighbourhoods (WGS84)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return tuple(self.geom.bounds)  # type: ignore[return-value]

    def buffered(self, metres: float) -> BaseGeometry:
        """The area grown by some distance, e.g. to catch nearby transit stops."""
        s = gpd.GeoSeries([self.geom], crs=WGS84).to_crs(METRIC_CRS).buffer(metres)
        return s.to_crs(WGS84).iloc[0]


def load_area(ids: list[int]) -> Area:
    path = toronto_resource(
        "neighbourhoods", "Neighbourhoods - 4326.geojson", "neighbourhoods.geojson"
    )
    all_ = gpd.read_file(path)
    all_["id"] = all_["AREA_SHORT_CODE"].astype(int)
    picked = all_[all_["id"].isin(ids)]
    missing = set(ids) - set(picked["id"])
    if missing:
        raise ValueError(f"unknown neighbourhood ids: {sorted(missing)}")
    gdf = picked[["id", "AREA_NAME", "geometry"]].rename(columns={"AREA_NAME": "name"})
    gdf = gdf.set_geometry(gdf.geometry.apply(as_multipolygon)).set_crs(WGS84, allow_override=True)
    return Area(gdf.reset_index(drop=True), gdf.geometry.union_all())


def as_multipolygon(g: BaseGeometry) -> BaseGeometry:
    return MultiPolygon([g]) if isinstance(g, Polygon) else g
