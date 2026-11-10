-- Ward: PostgreSQL schema (PostGIS + pgvector)
-- All geometries are WGS84 (SRID 4326). Feature IDs are stable strings like 'building:12345'.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()

-- =========================================================
-- 1. CITY DATA (loaded by the offline ingest pipeline)
-- =========================================================

CREATE TABLE neighbourhoods (
  id          INT PRIMARY KEY,               -- city's official neighbourhood number
  name        TEXT NOT NULL,
  geom        GEOMETRY(MultiPolygon, 4326) NOT NULL
);

-- Census areas (tracts or dissemination areas). Area-level aggregates only.
CREATE TABLE census_areas (
  dguid             TEXT PRIMARY KEY,         -- StatCan geographic ID
  level             TEXT NOT NULL,            -- 'CT' or 'DA'
  neighbourhood_id  INT REFERENCES neighbourhoods(id),
  population        INT,
  median_age        REAL,
  pct_renters       REAL,
  pct_transit       REAL,                     -- share commuting by transit
  avg_household     REAL,
  age_dist          JSONB,                    -- {"0-14": 0.12, "15-24": ...}
  housing_dist      JSONB,                    -- {"apartment": 0.7, "house": 0.2, ...}
  occupation_dist   JSONB,
  language_dist     JSONB,
  commute_dist      JSONB,                    -- {"car": 0.4, "transit": 0.3, "walk": ...}
  household_dist    JSONB,                    -- {"1": 0.5, "2": 0.3, ..., "5+": 0.01}
  geom              GEOMETRY(MultiPolygon, 4326) NOT NULL
);

CREATE TABLE buildings (
  fid        TEXT PRIMARY KEY,                -- 'building:<id>'
  height_m   REAL,
  use        TEXT,                            -- residential, commercial, mixed, ...
  name       TEXT,                            -- e.g. 'Rogers Centre'
  geom       GEOMETRY(MultiPolygon, 4326) NOT NULL
);

CREATE TABLE parcels (
  fid        TEXT PRIMARY KEY,                -- 'parcel:<id>'
  address    TEXT,
  area_m2    REAL,
  geom       GEOMETRY(MultiPolygon, 4326) NOT NULL
);

CREATE TABLE zoning (
  id            SERIAL PRIMARY KEY,
  zone_code     TEXT NOT NULL,                -- e.g. 'CR', 'RD'
  zone_class    TEXT,                         -- residential, commercial, open space, ...
  max_height_m  REAL,
  max_density   REAL,
  geom          GEOMETRY(MultiPolygon, 4326) NOT NULL
);

CREATE TABLE streets (
  fid         TEXT PRIMARY KEY,               -- 'street:<id>'
  name        TEXT,
  road_class  TEXT,                           -- arterial, collector, local, ...
  source      BIGINT,                         -- pgRouting graph nodes
  target      BIGINT,
  length_m    REAL,
  geom        GEOMETRY(LineString, 4326) NOT NULL
);

CREATE TABLE parks (
  fid       TEXT PRIMARY KEY,                 -- 'park:<id>'
  name      TEXT,
  area_m2   REAL,
  geom      GEOMETRY(MultiPolygon, 4326) NOT NULL
);

CREATE TABLE cycling (
  fid            TEXT PRIMARY KEY,            -- 'cycling:<id>'
  facility_type  TEXT,                        -- painted, protected, trail, ...
  geom           GEOMETRY(MultiLineString, 4326) NOT NULL
);

CREATE TABLE transit_stops (
  fid        TEXT PRIMARY KEY,                -- 'transit:<stop_id>'
  name       TEXT,
  mode       TEXT,                            -- subway, streetcar, bus, lrt
  routes     TEXT[],
  geom       GEOMETRY(Point, 4326) NOT NULL
);

CREATE TABLE pois (
  fid        TEXT PRIMARY KEY,                -- 'poi:<osm_id>'
  category   TEXT,                            -- school, grocery, library, clinic, ...
  name       TEXT,
  geom       GEOMETRY(Point, 4326) NOT NULL
);

-- =========================================================
-- 2. PERSONAS (generated on demand per area, then reused)
-- =========================================================

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

-- =========================================================
-- 3. PROPOSALS AND RESULTS
-- =========================================================

CREATE TABLE proposals (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id   TEXT,                          -- anonymous user/session
  parent_id    UUID REFERENCES proposals(id), -- previous version when refined
  prompt       TEXT,                          -- what the user typed
  type         TEXT NOT NULL,                 -- key from the type catalog
  params       JSONB,                         -- {"height_m": 90, "floors": 25}
  components   JSONB,                         -- mixed-use parts
  replaces     TEXT[],                        -- fids removed by this proposal
  geom         GEOMETRY(Geometry, 4326) NOT NULL,  -- polygon, line, or point
  status       TEXT DEFAULT 'draft',          -- draft, analyzing, done, failed
  fact_sheet   JSONB,                         -- computed metrics
  created_at   TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE pros_cons (
  proposal_id  UUID PRIMARY KEY REFERENCES proposals(id) ON DELETE CASCADE,
  pros         JSONB,
  cons         JSONB,
  model        TEXT
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

-- =========================================================
-- 4. REAL CONSULTATION DATA (RAG + evaluation)
-- =========================================================

CREATE TABLE applications (
  id             TEXT PRIMARY KEY,            -- city application number
  address        TEXT,
  description    TEXT,
  proposal_type  TEXT,                        -- mapped to a catalog type when possible
  geom           GEOMETRY(Geometry, 4326),
  decided_at     DATE
);

CREATE TABLE consultation_comments (
  id                SERIAL PRIMARY KEY,
  application_id    TEXT REFERENCES applications(id),
  neighbourhood_id  INT REFERENCES neighbourhoods(id),
  body              TEXT NOT NULL,            -- de-identified comment text
  themes            TEXT[],                   -- filled by theme extraction
  embedding         VECTOR(1024),             -- match your embedding model's dimension
  geom              GEOMETRY(Point, 4326)
);

-- =========================================================
-- 5. EVALUATION
-- =========================================================

CREATE TABLE eval_runs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  application_id  TEXT REFERENCES applications(id),
  proposal_id     UUID REFERENCES proposals(id),   -- the replayed proposal
  config          JSONB,                            -- models, persona count, prompt version
  created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE eval_metrics (
  run_id     UUID REFERENCES eval_runs(id) ON DELETE CASCADE,
  metric     TEXT NOT NULL,                   -- coverage, crime_mention_gap, stance_variance, ...
  slice      TEXT DEFAULT 'all',              -- 'all', 'model:grok', 'neighbourhood:27', ...
  value      REAL,
  PRIMARY KEY (run_id, metric, slice)
);

-- =========================================================
-- INDEXES
-- =========================================================

CREATE INDEX ON neighbourhoods        USING GIST (geom);
CREATE INDEX ON census_areas          USING GIST (geom);
CREATE INDEX ON buildings             USING GIST (geom);
CREATE INDEX ON parcels               USING GIST (geom);
CREATE INDEX ON zoning                USING GIST (geom);
CREATE INDEX ON streets               USING GIST (geom);
CREATE INDEX ON parks                 USING GIST (geom);
CREATE INDEX ON cycling               USING GIST (geom);
CREATE INDEX ON transit_stops         USING GIST (geom);
CREATE INDEX ON pois                  USING GIST (geom);
CREATE INDEX ON personas              USING GIST (home);
CREATE INDEX ON proposals             USING GIST (geom);
CREATE INDEX ON consultation_comments USING GIST (geom);

CREATE INDEX ON personas (neighbourhood_id);
CREATE INDEX ON persona_reactions (proposal_id);
CREATE INDEX ON consultation_comments (neighbourhood_id);
CREATE INDEX ON consultation_comments USING hnsw (embedding vector_cosine_ops);