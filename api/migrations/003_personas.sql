-- Phase 4: personas, the places they use, and their reactions to proposals.
-- Persona tables copied verbatim from docs/ward_schema.sql.

-- Census shares personas are sampled from: main commute mode and household size.
ALTER TABLE census_areas ADD COLUMN commute_dist JSONB;     -- {"car": 0.4, "transit": 0.3, ...}
ALTER TABLE census_areas ADD COLUMN household_dist JSONB;   -- {"1": 0.5, "2": 0.3, ..., "5+": 0.01}

CREATE TABLE personas (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  dguid             TEXT REFERENCES census_areas(dguid),
  neighbourhood_id  INT REFERENCES neighbourhoods(id),
  role              TEXT NOT NULL,            -- resident, worker, visitor, citywide
  name              TEXT NOT NULL,
  age               INT,
  tenure            TEXT,                     -- renter, owner
  commute_mode      TEXT,                     -- transit, car, bike, walk
  occupation        TEXT,
  household         TEXT,                     -- e.g. 'couple with two kids'
  values_list       TEXT[],                   -- ['community', 'affordability']
  traits            JSONB,                    -- openness, trust_in_government, ...
  stubbornness      REAL DEFAULT 0.5,         -- 0..1, used by town hall stance updates
  backstory         TEXT,
  model             TEXT NOT NULL,            -- fixed per persona, e.g. 'anthropic/claude-haiku'
  home              GEOMETRY(Point, 4326),    -- approximate, random point in their area
  created_at        TIMESTAMPTZ DEFAULT now()
);

-- Places a persona uses regularly (parks, stops, stores, landmarks)
CREATE TABLE persona_places (
  persona_id   UUID REFERENCES personas(id) ON DELETE CASCADE,
  place_fid    TEXT NOT NULL,                 -- any feature fid
  relation     TEXT,                          -- 'commutes from', 'walks dog at', 'childhood memories'
  PRIMARY KEY (persona_id, place_fid)
);

CREATE TABLE persona_reactions (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  proposal_id  UUID REFERENCES proposals(id) ON DELETE CASCADE,
  persona_id   UUID REFERENCES personas(id),
  model        TEXT NOT NULL,
  stance       REAL,                          -- -1 (opposed) .. 1 (supportive)
  reasons      TEXT[],
  quote        TEXT,
  raw          JSONB,                         -- full model output for debugging
  latency_ms   INT,
  created_at   TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ON personas (neighbourhood_id);
CREATE INDEX ON personas USING GIST (home);
CREATE INDEX ON persona_reactions (proposal_id);
