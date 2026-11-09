"""TTC stops from the GTFS feed, with the routes and mode serving each one."""

import io
import logging
import zipfile

import geopandas as gpd
import pandas as pd
from sqlalchemy import Engine

from ..area import Area
from ..cache import toronto_resource
from ..config import WGS84
from ..db import upsert

log = logging.getLogger(__name__)

# Stops just outside the area still count as "nearest" for buildings near its edge.
BUFFER_M = 600
MODES = {0: "streetcar", 1: "subway", 2: "rail", 3: "bus"}
MODE_RANK = ["subway", "lrt", "streetcar", "rail", "bus"]
LRT_ROUTES = {"5", "6"}  # Eglinton Crosstown, Finch West


def ingest(eng: Engine, area: Area) -> int:
    path = toronto_resource(
        "ttc-routes-and-schedules", "TTC Routes and Schedules Data", "ttc-gtfs.zip"
    )
    with zipfile.ZipFile(path) as z:

        def read(name: str, cols: list[str]) -> pd.DataFrame:
            return pd.read_csv(io.BytesIO(z.read(name)), usecols=cols, dtype=str)

        stops = read("stops.txt", ["stop_id", "stop_name", "stop_lat", "stop_lon"])
        gstops = gpd.GeoDataFrame(
            stops,
            crs=WGS84,
            geometry=gpd.points_from_xy(stops.stop_lon.astype(float), stops.stop_lat.astype(float)),
        )
        gstops = gstops[gstops.within(area.buffered(BUFFER_M))]
        wanted = set(gstops.stop_id)

        stop_times = pd.concat(
            chunk[chunk.stop_id.isin(wanted)]
            for chunk in pd.read_csv(
                io.BytesIO(z.read("stop_times.txt")),
                usecols=["trip_id", "stop_id"],
                dtype=str,
                chunksize=1_000_000,
            )
        ).drop_duplicates()
        trips = read("trips.txt", ["trip_id", "route_id"])
        routes = read("routes.txt", ["route_id", "route_short_name", "route_type"])

    served = stop_times.merge(trips, on="trip_id").merge(routes, on="route_id")
    served["mode"] = [
        "lrt" if name in LRT_ROUTES else MODES.get(int(t), "bus")
        for name, t in zip(served.route_short_name, served.route_type, strict=True)
    ]
    by_stop = served.groupby("stop_id").agg(
        routes=("route_short_name", lambda s: sorted(set(s), key=_route_key)),
        mode=("mode", lambda s: min(set(s), key=MODE_RANK.index)),
    )
    gdf = gstops.join(by_stop, on="stop_id", how="inner")
    gdf = gdf.assign(
        fid="transit:" + gdf.stop_id,
        name=gdf.stop_name,
        routes=gdf.routes.map(lambda r: "{" + ",".join(f'"{x}"' for x in r) + "}"),
    )
    log.info("transit: %d stops", len(gdf))
    return upsert(eng, gdf[["fid", "name", "mode", "routes", "geometry"]], "transit_stops", "fid")


def _route_key(route: str) -> tuple[int, str]:
    return (int(route), "") if route.isdigit() else (10_000, route)
