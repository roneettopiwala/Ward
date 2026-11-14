"""Build map tiles from Postgres: one PMTiles file per layer, with Ward fids.

  python -m ward_pipeline.tiles                    every layer
  python -m ward_pipeline.tiles buildings parks    just these

Each layer is streamed out of Postgres as newline-delimited GeoJSON and tiled
with Tippecanoe. Every feature keeps its fid as a property, so the map can use
it as the feature id (MapLibre promoteId). Output goes to web/public/tiles/,
which the web app serves as static files.
"""

import argparse
import logging
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

from .config import DATABASE_URL, ROOT

log = logging.getLogger("ward_pipeline.tiles")

OUT_DIR = ROOT.parent / "web" / "public" / "tiles"


@dataclass(frozen=True)
class Layer:
    table: str
    # Property name -> SQL expression.
    props: dict[str, str]
    minzoom: int
    maxzoom: int
    options: list[str] = field(default_factory=list)


# Layers drop features only where tiles get too dense at low zoom; from
# maxzoom up, every feature is present (MapLibre overzooms past maxzoom).
LAYERS: dict[str, Layer] = {
    "buildings": Layer(
        "buildings",
        {"fid": "fid", "height": "round(height_m::numeric, 1)", "use": "use", "name": "name"},
        12,
        15,
        ["--drop-densest-as-needed", "--simplify-only-low-zooms"],
    ),
    "parcels": Layer(
        "parcels",
        {"fid": "fid", "address": "address", "area_m2": "round(area_m2::numeric)"},
        14,
        15,
        ["--drop-densest-as-needed", "--simplify-only-low-zooms"],
    ),
    "streets": Layer(
        "streets",
        {"fid": "fid", "name": "name", "road_class": "road_class"},
        10,
        15,
        ["--drop-densest-as-needed"],
    ),
    "parks": Layer(
        "parks",
        {"fid": "fid", "name": "name", "area_m2": "round(area_m2::numeric)"},
        10,
        15,
        ["--coalesce-densest-as-needed"],
    ),
    "cycling": Layer(
        "cycling",
        {"fid": "fid", "name": "name", "facility_type": "facility_type"},
        10,
        15,
        [],
    ),
    "transit": Layer(
        "transit_stops",
        {"fid": "fid", "name": "name", "mode": "mode"},
        11,
        15,
        ["-r1"],
    ),
}


def build(name: str, layer: Layer, workdir: Path) -> Path:
    started = time.monotonic()
    ndjson = workdir / f"{name}.ndjson"
    props = ", ".join(f"'{k}', {v}" for k, v in layer.props.items())
    query = (
        "SELECT json_build_object('type', 'Feature', "
        f"'properties', json_strip_nulls(json_build_object({props})), "
        "'geometry', ST_AsGeoJSON(geom, 7)::json)::text "
        f"FROM {layer.table}"
    )
    count = 0
    with psycopg.connect(_libpq_url()) as conn, conn.cursor(name=f"export_{name}") as cur:
        cur.itersize = 5000
        cur.execute(query)
        with ndjson.open("w") as f:
            for (row,) in cur:
                f.write(row)
                f.write("\n")
                count += 1
    out = OUT_DIR / f"{name}.pmtiles"
    tmp = workdir / out.name
    subprocess.run(
        [
            "tippecanoe",
            "--quiet",
            "--force",
            "-P",  # parallel read of newline-delimited GeoJSON
            "-l",
            name,
            "-Z",
            str(layer.minzoom),
            "-z",
            str(layer.maxzoom),
            "-o",
            str(tmp),
            *layer.options,
            str(ndjson),
        ],
        check=True,
    )
    ndjson.unlink()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.move(tmp, out)  # replace in one step so the map never reads a half-written file
    size_mb = out.stat().st_size / 1e6
    log.info("%s: %d features, %.1f MB, %.0fs", name, count, size_mb, time.monotonic() - started)
    return out


def _libpq_url() -> str:
    # The pipeline's SQLAlchemy URL names a driver ("postgresql+psycopg://"); libpq doesn't.
    return DATABASE_URL.replace("+psycopg", "").replace("+psycopg2", "")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("layers", nargs="*", help=f"any of {', '.join(LAYERS)}; default: all")
    args = parser.parse_args()
    if unknown := set(args.layers) - set(LAYERS):
        parser.error(f"unknown layers: {', '.join(sorted(unknown))}")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    if not shutil.which("tippecanoe"):
        raise SystemExit("tippecanoe not found: sudo apt install tippecanoe")
    with tempfile.TemporaryDirectory(prefix="ward-tiles-") as tmp:
        for name in args.layers or LAYERS:
            build(name, LAYERS[name], Path(tmp))


if __name__ == "__main__":
    main()
