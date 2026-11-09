# Phase 3: Fact sheet and pros/cons

## Goal
After choosing what to build, the user gets a data-driven pros and cons list
streamed into the results panel.

## Designs
Results panel pages of the design PDF: header, overall summary area,
pros and cons section. Persona cards come in Phase 4.

## In scope
- Type catalog in api/catalog/ with 3 types: condo, mall, park
  (geometry, params with defaults, render style, impact_metrics, relevant_to)
- "Replace" on the selected-building card opens a simple type picker with
  the type's main params (e.g. height for condo). Temporary until Phase 5.
- Proposals render with the catalog's style (park flat green, buildings
  extruded by height)
- POST /proposals: validates the proposal, stores it, runs analysis
- Spatial query service (PostGIS) for the catalog's impact metrics, e.g.:
  zoning fit and height vs. max, height vs. neighbours, transit within
  500 m, parks/schools nearby, green space per resident, population in the
  impact radius, what is being replaced
- Fact sheet builder: one JSON object of computed metrics, saved on the
  proposal
- One LLM client wrapper (LiteLLM, single model for now) used by all calls
- Pros/cons prompt in api/services/prompts/, structured output validated
  with Pydantic, retried once on failure
- Server-sent events: proposal status, pros/cons, done, error
- Redis cache keyed by proposal type + params + geometry hash
- Impact radius ring on the map around the proposal

## Out of scope
- Personas (Phase 4)
- Prompt bar and parsing (Phase 5)
- Types beyond condo, mall, park (Phase 6)

## Design for later
- The analysis pipeline is a plain async function taking a proposal, so the
  Phase 8 eval script can call it without the frontend.
- Every number shown comes from the fact sheet. The LLM may only phrase
  facts, never invent them.

## Done when
Replacing the Rogers Centre with a mall, or a nearby lot with a condo,
streams a pros and cons list where every claim traces to a fact sheet value.
