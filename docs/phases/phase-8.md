# Phase 8: Broad building types

## Goal
Users can propose almost any building or piece of city infrastructure in
plain language, and Ward analyses it as what it is: a school is a school, not
a mall tagged "school".

## Why
The catalog has six types (condo, mall, park, community garden, bike lane,
transit station). Anything else is mapped to the closest one plus tags, so an
office tower is analysed as homes and a library as retail. One YAML file and
hand-written metrics per type won't reach "almost anything".

## In scope
- Use classes: about 15 to 20 classes, each a catalog file with its params,
  draw rules, render style, impact metrics and persona relevance. Specific
  buildings are subtypes of a class (defaults and labels), and tags keep the
  details. Starting list, to confirm:

  | Class | Example subtypes |
  |---|---|
  | Residential | condo tower, mid-rise rental, townhouses, seniors' or student housing |
  | Office | office tower, lab, studio |
  | Retail and food | grocery, mall, shops, restaurants, food hall |
  | Hotel | hotel |
  | School | elementary, secondary, college building |
  | Health | hospital wing, clinic, long-term care |
  | Community | library, community centre, place of worship, daycare |
  | Recreation and venue | arena, stadium, theatre, pool, rec centre |
  | Industrial | warehouse, factory, data centre |
  | Civic and utility | fire station, police station, transit yard |
  | Parking | parking garage, surface lot |
  | Open space | park, plaza, community garden |
  | Street changes | bike lane, pedestrianised street, bus lane |
  | Transit | station |

- Existing six types move into classes; stored proposals still load and replay.
- Mixed use keeps working: parts from different classes stack on one site.
- Parser: a prompt maps to a class and subtype. Something unknown ("a cat
  café") goes to the closest class with a free-text subtype, never to an
  unrelated class; assumptions say what was chosen.
- Metrics computed in code, shared within a class: homes and residents, jobs,
  daily visitors or trips, capacity and event-day crowds, students or
  patients served, truck traffic, as each class needs. Every planning rate
  (e.g. jobs per m² of office) cites its source in a data file, like
  api/data/interests.yaml.
- Fact sheet, pros/cons and context use the class's facts.
- Map: a render style per class (colour, extrusion or line), and drawing
  tools that fit each class's geometry.
- Personas: relevance groups per class, so a school draws parents and a
  warehouse draws nearby residents and drivers.

## Out of scope
- New transit lines (streetcar, LRT, subway): stops, ridership and network
  effects make them a project of their own; a later phase
- Traffic simulation or rerouting for street changes (facts only)
- Costs, construction schedules, approvals
- Places outside the City of Toronto

## Steps (one branch and PR each)
1. `phase-8/classes`: class and subtype model, migrate the six types, parser
   (anything without a class yet gets a clarification, not a wrong class)
2. `phase-8/new-classes`: the remaining classes with the shared facts every
   building has (what it replaces, height context, zoning fit, transit,
   floor area, population), plus a parser test set of about 30 prompts
3. `phase-8/metrics`: class-specific facts and the cited rates file
4. `phase-8/map`: render styles and draw rules per class, and a type picker
   that copes with many classes
5. `phase-8/personas`: persona relevance per class
6. `phase-8/subtypes-*`: remaining subtypes in batches

## Persona rules
Unchanged from Phase 7: no reputation labels, safety concerns only from a
persona's own situation, quotes 1 to 3 sentences in plain English.

## Done when
Twenty varied prompts (e.g. "a public library", "an elementary school", "a
30-storey office tower", "a warehouse", "a hockey arena", "townhouses", "a
fire station", "a plaza", "a parking garage", "a bus lane on Queen")
are each analysed as that kind of building, with facts that fit it and
personas who care about it, and none of them silently becomes a condo,
mall or park.
