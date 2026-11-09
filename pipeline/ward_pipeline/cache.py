"""Download-once cache for raw source files."""

import logging
from pathlib import Path

import httpx

from .config import CACHE_DIR

log = logging.getLogger(__name__)

CKAN = "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/package_show"


def cached(name: str, url: str) -> Path:
    """Return the cached file, downloading it first if needed."""
    path = CACHE_DIR / name
    if path.exists():
        return path
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    log.info("downloading %s", url)
    tmp = path.with_suffix(path.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=600) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    tmp.rename(path)
    return path


def toronto_resource(package: str, resource: str, name: str) -> Path:
    """A file from Toronto Open Data, found by package and resource name."""
    path = CACHE_DIR / name
    if path.exists():
        return path
    meta = httpx.get(CKAN, params={"id": package}, timeout=60).raise_for_status().json()
    for r in meta["result"]["resources"]:
        if r["name"] == resource:
            return cached(name, r["url"])
    raise LookupError(f"{package}: no resource named {resource!r}")
