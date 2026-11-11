# Phase 5: Prompt bar

## Goal
Users describe what they want in plain language instead of using the type
picker, then adjust an editable preview before analyzing.

## Designs
Prompt bar and proposal preview pages of the design PDF.

## In scope
- Prompt bar appears after a selection (replaces the Phase 3 type picker)
- POST /proposals/parse: selection context + prompt -> catalog JSON
  (type, params, components, replaces_existing, assumptions, clarification)
- Fast model, structured output, validated against the catalog
- Mixed use via components ("condo with a grocery store on the ground floor")
- Out-of-catalog requests map to the closest type plus descriptive tags
- Clarification question only when the model truly can't decide
- Preview card: editable chips and sliders for type and params, with
  assumptions shown; live map preview
- After analysis, two ways to change the proposal:
  - Edit: a button on the results reopens the preview card with its
    chips and sliders, for exact adjustments (e.g. height to 38 storeys)
  - Refine: follow-up prompts in the prompt bar edit the current proposal
    in plain language ("make it half as tall")
  Both open an updated preview before re-analyzing, and new versions link
  via parent_id
- Show previous vs. new overall sentiment after either kind of change

## Out of scope
- New catalog types or drawing tools (Phase 6)

## Done when
Selecting the Rogers Centre and typing "a mall with a rooftop park and a food
hall" produces a sensible preview, analyzes correctly, and a follow-up like
"make it 2 storeys shorter" updates it and shows the sentiment change.
