# Phase 4: Personas v1 (MVP)

## Goal
Local AI personas react to a proposal, and their reactions stream into the
results panel with an overall sentiment. This completes the core loop.

## Designs
Persona card and overall sentiment pages of the design PDF.

## In scope
- Persona generator (Sonnet-class model, runs once per area):
  - sample attributes from census distributions for the area
  - mix of roles: mostly residents, plus nearby workers and visitors
  - assign 2 to 4 routine places from POIs, parks and stops
  - flesh out name, backstory, values, a few non-obvious traits
  - random home point inside the persona's census area
  - store in personas and persona_places
- About 15 personas for the test area, generated on first use and reused
- Persona selection per proposal using area + the catalog's relevant_to
- Personal impact computed in code per persona: distance from home,
  affected routine places, lost places, commute effects
- Reaction prompt: profile + fact sheet + personal impact.
  Output: stance (-1..1), top 2 reasons, 1 to 3 sentence quote.
- Single fast model for reactions, called in parallel; Pydantic validation
  and one retry
- Aggregate: overall sentiment, share for/against, top themes
- Stream each persona card as it finishes, then the aggregate
- Save reactions in persona_reactions

## Out of scope
- Multiple models, RAG over real comments (Phase 7)
- Town hall (Phase 10)
- Other areas (Phase 6)

## Persona rules
- Personas come from data only. No reputation labels in any prompt.
- Nothing maps to real individuals.

## Done when
The full loop works in the test area: select, replace, get pros/cons and
around 15 distinct persona reactions with an overall sentiment.
Record a short demo video.
