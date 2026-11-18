"""Ingest city data.

python -m ward_pipeline --area 165[,164,...]   one or more neighbourhoods
python -m ward_pipeline --area all             the whole city, one neighbourhood at a
                                               time; resumes where a previous run stopped
python -m ward_pipeline --only streets,cycling  just these citywide sources
python -m ward_pipeline --only applications,consultation  development applications and
                                               residents' comments from staff reports
python -m ward_pipeline --only embeddings      embed comments that have no vector yet
python -m ward_pipeline --only heritage,landmarks  heritage register; notable OSM places
                                               with Wikidata facts
python -m ward_pipeline --area 165 --only census  reload census for an area
"""

import argparse
import gc
import logging
import time

from sqlalchemy import Engine, text

from . import migrate
from .area import all_ids, load_area
from .db import engine
from .sources import (
    addresses,
    applications,
    buildings,
    census,
    consultation,
    cycling,
    embeddings,
    heritage,
    landmarks,
    neighbourhoods,
    osm,
    parcels,
    parks,
    streets,
    transit,
    zoning,
)

log = logging.getLogger("ward_pipeline")

CITYWIDE = {
    "streets": streets.ingest,
    "cycling": cycling.ingest,
    # Comments are located at their applications, so applications go first.
    "applications": applications.ingest,
    "consultation": consultation.ingest,
    "embeddings": embeddings.ingest,
    "heritage": heritage.ingest,
    "landmarks": landmarks.ingest,
}
ONLY = ["census", *CITYWIDE]
# After a neighbourhood fails, wait this long before the next one.
FAILURE_PAUSE_S = 60


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--area", help="neighbourhood numbers, e.g. 165,164, or 'all'")
    parser.add_argument("--only", help=f"comma-separated sources to (re)load: {', '.join(ONLY)}")
    parser.add_argument(
        "--force", action="store_true", help="with --area all: redo finished neighbourhoods"
    )
    args = parser.parse_args()
    only = [s.strip() for s in args.only.split(",")] if args.only else []
    if unknown := set(only) - set(ONLY):
        parser.error(f"unknown --only sources: {', '.join(sorted(unknown))}")
    if not args.area and not only:
        parser.error("give --area, --only, or both")
    if "census" in only and not args.area:
        parser.error("--only census needs --area")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    eng = engine()
    migrate.migrate(eng)

    wanted = set(only) or (set(CITYWIDE) if args.area == "all" else set())
    citywide = [s for s in CITYWIDE if s in wanted]
    for name in citywide:
        log.info("%s: %d rows", name, CITYWIDE[name](eng))

    if not args.area:
        return
    if args.area == "all":
        _all(eng, census_only="census" in only, force=args.force)
    elif not only or "census" in only:
        ids = sorted(int(x) for x in args.area.split(","))
        ingest_area(eng, ids, census_only="census" in only)
    log.info("done")


def ingest_area(eng: Engine, ids: list[int], census_only: bool = False) -> None:
    area = load_area(ids)
    log.info("area: %s", ", ".join(area.neighbourhoods["name"]))
    neighbourhoods.ingest(eng, area)
    census.ingest(eng, area)
    if census_only:
        return
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


def _all(eng: Engine, census_only: bool, force: bool) -> None:
    """Every neighbourhood, one at a time to keep memory low. Failures are logged and
    skipped; rerunning picks them up because only finished neighbourhoods are logged."""
    with eng.connect() as conn:
        logged = conn.scalars(text("SELECT neighbourhood_id FROM ingest_log"))
        done = set() if force else set(logged)
    ids = all_ids()
    # Every boundary first, so the app can tell which areas are still to come.
    neighbourhoods.ingest(eng, load_area(ids))
    todo = [i for i in ids if census_only or i not in done]
    log.info("citywide: %d neighbourhoods to do, %d already done", len(todo), len(done))
    failed: list[int] = []
    for n, nid in enumerate(todo, 1):
        started = time.monotonic()
        log.info("[%d/%d] neighbourhood %d", n, len(todo), nid)
        try:
            ingest_area(eng, [nid], census_only=census_only)
        except Exception:
            log.exception("neighbourhood %d failed; rerun to retry it", nid)
            failed.append(nid)
            # A network blip shouldn't fail every neighbourhood after it; wait it out.
            time.sleep(FAILURE_PAUSE_S)
            continue
        finally:
            gc.collect()
        if not census_only:
            with eng.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO ingest_log (neighbourhood_id) VALUES (:id) "
                        "ON CONFLICT (neighbourhood_id) DO UPDATE SET finished_at = now()"
                    ),
                    {"id": nid},
                )
        took = time.monotonic() - started
        log.info("[%d/%d] neighbourhood %d took %.0fs", n, len(todo), nid, took)
    if failed:
        log.warning("failed: %s. Run again to retry.", ",".join(map(str, failed)))


if __name__ == "__main__":
    main()
