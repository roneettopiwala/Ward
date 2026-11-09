# Phase 1: The map

## Goal
A 2.5D map of Toronto where you can click a building, remove it, and place a
placeholder block in its spot.

## Designs
The design PDF in docs/design/ (rename the path here if yours differs:
docs/design/ward.pdf) is the visual reference for the whole app.

- Before planning, read the whole PDF and list which pages cover the
  Phase 1 screens: the default map view and the building-selected state
  (highlight, popover with Remove/Replace, placeholder block, removed outline).
- Build only those screens now. Pages showing the prompt bar, preview,
  results panel or persona cards are for later phases.
- Extract colours, fonts, spacing and corner radius from the PDF into the
  Tailwind config (light and dark if shown), and use those tokens everywhere.
- Set up the app shell from the PDF: map area, where the side panel will
  sit, floating toolbar position.
- Match the PDF's layout and tokens. Close is enough for now; pixel-level
  polish (exact spacing, animations, hover states) happens in Phase 9.
- If something in the PDF conflicts with this brief or is unclear, ask
  before deviating.

## Assumes (Phase 0 done)
- Next.js app in web/ and FastAPI app in api/ both run locally
- Docker Compose starts PostGIS and Redis
- The health page shows green for API, Postgres and Redis

## In scope
- MapLibre GL JS map centred on downtown Toronto, with pitch and rotation
- OpenFreeMap basemap, with its buildings rendered as fill-extrusion by height
- Map state in a Zustand store: selected fid, removed fids, proposals
- Click a building: highlight it with feature-state and show its basic
  properties (and a name if the basemap POI layer has one inside it)
- Small popover with Remove and Replace
- Remove: add the fid to the removed set and hide it with a layer filter
- Replace: remove, then add a proposal using the old footprint
- Proposals render from their own GeoJSON source as extrusions in the
  accent colour from the design tokens, with a fixed placeholder height
- Removed buildings show as a dashed outline
- Undo for the last action
- Styling from the Tailwind config tokens, matching the Phase 1 pages of the design PDF

## Build order
Check each step in the browser before moving on:
1. Map with 2.5D buildings centred downtown
2. Click to highlight and show properties
3. Remove
4. Replace with a placeholder block
5. Dashed outline for removed buildings
6. Undo

## Out of scope
- Any backend data or PostGIS queries (Phase 2)
- Drawing new shapes on empty lots (Phase 6)
- Choosing a building type, prompt bar, pros/cons, personas (Phases 3 to 5)
- PMTiles or official city data (Phase 6)

## Design for later
- Read basemap feature IDs only in one adapter module, since Phase 6 replaces
  them with our own fids.
- Store proposals as plain objects (type, params, geometry, replaces) so a
  parsed prompt can create them later.
- Don't assume proposal geometry is always a polygon.

## Done when
You can click the Rogers Centre, remove it, place a block where it was,
see the old outline, and undo it, and the layout and colours roughly match
the Phase 1 pages of the design PDF.
