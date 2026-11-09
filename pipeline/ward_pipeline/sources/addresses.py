"""Toronto address points. Not stored: used to address parcels and name buildings."""

import logging

import geopandas as gpd

from ..area import Area
from ..cache import toronto_resource

log = logging.getLogger(__name__)


def load(area: Area) -> gpd.GeoDataFrame:
    path = toronto_resource(
        "address-points-municipal-toronto-one-address-repository",
        "Address Points - 4326.gpkg",
        "addresses.gpkg",
    )
    cols = ["ADDRESS_FULL", "PLACE_NAME", "LO_NUM", "ADDRESS_CLASS_DESC"]
    gdf = gpd.read_file(path, columns=cols, mask=area.geom)
    gdf = gdf.explode(index_parts=False).reset_index(drop=True)
    gdf = gdf.rename(
        columns={
            "ADDRESS_FULL": "address",
            "PLACE_NAME": "place_name",
            "LO_NUM": "number",
            "ADDRESS_CLASS_DESC": "address_class",
        }
    )
    # The source writes blank place names as the text "None".
    gdf["place_name"] = gdf["place_name"].where(~gdf["place_name"].isin(["None", ""]))
    # Best first: named places (a venue's official address), then land addresses,
    # then the lowest street number.
    gdf["rank"] = gdf["place_name"].isna().astype(int) * 2 + (gdf["address_class"] != "Land")
    gdf = gdf.sort_values(["rank", "number"]).drop(columns="rank")
    log.info("addresses: %d points", len(gdf))
    return gdf
