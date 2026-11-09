# Phase 2: Data for one area

## Goal
Clicking a building shows real information about it from our own PostGIS
database, for one test area.

## Designs
Selected-building card from the design PDF, now with real values
(name, use, height, lot area, zoning).

## Area
The City of Toronto neighbourhood that contains the Rogers Centre. Add the
neighbourhoods directly next to it only if needed for nearby transit/POIs.

## In scope
- Ingest scripts in pipeline/ (GeoPandas, WGS84, stable fids) for this area:
  - neighbourhood boundary
  - census areas (tract or dissemination area level) with area aggregates
  - 3D massing buildings (height, use)
  - property parcels (address, area)
  - zoning (zone code, class, max height)
  - TTC stops from GTFS
  - named POIs from OpenStreetMap (via Overpass, this area only)
  - Toronto address points
- Only the tables from docs/ward_schema.sql that these need
- Building names via spatial join: POI name inside, else address, else a
  generated description ("3-storey residential building")
- Match basemap buildings to our buildings inside the basemap adapter
  (by location), so clicks resolve to our fids
- GET /features/{fid} returning name, use, height, lot area, zoning, and
  the 3 nearest TTC stops with distances
- Selected-building card shows this data; loading and not-found states

## Out of scope
- Fact sheet, pros/cons, personas (Phases 3 and 4)
- Any other part of the city (Phase 6)
- PMTiles (Phase 6)
- LLM calls of any kind

## Design for later
- Ingest scripts take an area (neighbourhood IDs) as a parameter, so Phase 6
  can run them citywide without rewriting.
- Keep raw downloads out of git; scripts download what they need.

## Done when
Clicking the Rogers Centre shows "Rogers Centre", its use, height, lot area,
zoning, and the closest TTC stops, all from PostGIS.
