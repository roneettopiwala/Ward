# Phase 6: Go citywide

## Goal
Every building and lot in the City of Toronto is selectable and editable,
with our own data, plus non-building infrastructure and drawing tools.

## Designs
Toolbar and drawing-state pages of the design PDF, plus any pages for parks,
bike lanes and stations.

## In scope
- Run Phase 2 ingest citywide (all 158 neighbourhoods)
- Add streets (centreline, with pgRouting graph), parks, cycling network
- Build PMTiles with Tippecanoe per layer (buildings, parcels, streets,
  parks, cycling, transit); host as static files; load in MapLibre with
  promoteId on our fids
- Replace basemap buildings with our building layer; retire the basemap
  feature ID adapter
- Click handling across layers with priority (buildings, points, lines,
  parks, parcels) and a chooser when they overlap
- Area resolver: proposal geometry -> neighbourhoods and census areas in
  the impact radius
- Personas generated on demand per area, then reused
- New catalog types: community garden, bike lane, transit station
  (keep condo, mall, park)
- Drawing tools from the catalog's draw rules:
  - areas: click an empty lot, rectangle, freehand polygon, snapping
  - lines: routed along streets between clicked points (pgRouting)
  - points: click, snapped to a valid spot
- Validation per type (size, length, inside Toronto, not on water/highways)
- Overlap prompt: "This overlaps N buildings. Remove them?"
- Catalog-specific fact sheet metrics for the new types

## Out of scope
- Multi-model personas and RAG (Phase 7)
- The 905 cities

## Done when
You can do the Rogers Centre, a park at Jane and Finch, and a bike lane in
Scarborough, each with local pros/cons and local personas.
