import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / ".cache"
MIGRATIONS_DIR = ROOT.parent / "api" / "migrations"

load_dotenv(ROOT / ".env")

DATABASE_URL = os.environ["DATABASE_URL"]

# Projected CRS for areas and distances (NAD83(CSRS) / MTM zone 10, Toronto).
METRIC_CRS = 2952
WGS84 = 4326
