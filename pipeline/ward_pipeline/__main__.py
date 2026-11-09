"""Ingest city data for an area: python -m ward_pipeline --area 165[,164,...]"""

import argparse
import logging

from . import migrate
from .area import load_area
from .db import engine
from .sources import (
    addresses,
    buildings,
    census,
    neighbourhoods,
    osm,
    parcels,
    parks,
    transit,
    zoning,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--area",
        required=True,
        help="comma-separated City of Toronto neighbourhood numbers, e.g. 165",
    )
    args = parser.parse_args()
    ids = sorted(int(x) for x in args.area.split(","))

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    log = logging.getLogger("ward_pipeline")

    eng = engine()
    migrate.migrate(eng)
    area = load_area(ids)
    log.info("area: %s", ", ".join(area.neighbourhoods["name"]))

    neighbourhoods.ingest(eng, area)
    census.ingest(eng, area)
    osm_data = osm.fetch(area, cache_key="-".join(map(str, ids)))
    osm.ingest_pois(eng, osm_data)
    address_points = addresses.load(area)
    parcel_rows = parcels.load(area, address_points)
    parcels.ingest(eng, parcel_rows)
    zones = zoning.load(area)
    zoning.ingest(eng, area, zones)
    transit.ingest(eng, area)
    parks.ingest(eng, area)
    buildings.ingest(eng, buildings.load(area, osm_data, address_points, parcel_rows, zones))
    log.info("done")


if __name__ == "__main__":
    main()
