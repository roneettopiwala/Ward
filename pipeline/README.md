# pipeline

Offline ingest for Ward. Loads city data for an area (one or more City of
Toronto neighbourhood numbers) into PostGIS.

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m ward_pipeline --area 165        # Harbourfront-CityPlace
```

Raw downloads are cached in `.cache/` (gitignored). Delete a file there to
re-download it. Re-running an area replaces that area's rows.

Sources: Toronto Open Data (neighbourhoods, 3D massing, property boundaries,
zoning by-law 569-2013, address points, TTC GTFS), OpenStreetMap via
Overpass (POIs and building tags), Statistics Canada 2021 Census (DA
boundaries and Census Profile).
