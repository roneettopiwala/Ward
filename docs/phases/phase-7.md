# Phase 7: Better personas

## Goal
Reactions feel specific, varied and grounded in what real residents of each
area actually say.

## In scope
- Collect public consultation comments from past Toronto development
  applications (TMMIS) since 2022, in two passes: first the community consultation
  sections of planning staff reports (already de-identified summaries of
  what residents raised), then residents' letters from the communications
  files (text PDFs only, de-identified, form letters collapsed). Store
  applications + comments, tagged with their source.
- Embed comments into pgvector with neighbourhood and location tags, using a
  local model (bge-small-en-v1.5 via fastembed; no API key). Store which
  model made each vector.
- Geo-filtered retrieval: similar comments from the persona's area are
  added to the prompt as tone and reasoning references
- Neighbourhood context card built from data only (demographics, recent
  developments, nearby places, common themes in local comments)
- One model for all persona reactions (Claude Sonnet), still routed through the LiteLLM client
  wrapper so the model is a config change. More models are considered only
  if Phase 9 eval shows reactions still sound alike.
- Persona voices: each persona gets a fixed voice (length, directness,
  reasoning style, temperature, opening), assigned in code when the persona
  is created: mostly a seeded random draw, lightly nudged by situation
  (e.g. parents of young kids lean short). Stored with the persona and
  added to the reaction prompt.
- Persona interests: 2 to 3 per persona, sampled in code from real
  participation rates and tied to real places (e.g. a fan who watches
  games at Rogers Centre). Landmark facts (OSM, Wikidata, heritage
  register) when a proposal replaces something significant. A few
  citywide personas for city-scale sites.
- JSON validation, retries, logged failures, length caps so cards look
  consistent
- Regenerate existing personas with the improved generator
- Track which model produced each reaction

## Persona rules
- No reputation labels in prompts or context cards, ever.
- Safety concerns may appear only when they follow from a persona's own
  situation, alongside their other concerns.
- Voices change how a persona argues, never who they are: no accents,
  dialect, slang or grammar based on ethnicity, language, income or
  neighbourhood. Quotes stay 1 to 3 sentences.

## Done when
The same proposal type in two different neighbourhoods produces clearly
different, locally grounded reactions, and personas reacting to the same
proposal sound like different people.
