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
  road_class  TEXT,                           -- expressway, ramp (expressway), arterial_ramp,
                                              -- major_arterial, minor_arterial, collector,
                                              -- local, laneway, access, busway, trail, walkway
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
  name           TEXT,                        -- street or trail name
  facility_type  TEXT,                        -- painted, protected, trail, shared
  installed      INT,                         -- year
  geom           GEOMETRY(MultiLineString, 4326) NOT NULL
);

-- Neighbourhoods the citywide ingest has finished, so a rerun can resume.
CREATE TABLE ingest_log (
  neighbourhood_id  INT PRIMARY KEY,
  finished_at       TIMESTAMPTZ NOT NULL DEFAULT now()
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
  context      JSONB,                         -- neighbourhood context cards used
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

-- Community Planning applications from Toronto Open Data, one row per application
-- (the dataset repeats an application once per address).
CREATE TABLE applications (
  application_number  TEXT PRIMARY KEY,       -- e.g. '23 214176 ESC 22 OZ'
  application_type    TEXT,                   -- OZ, SA, CD, SB, ...
  address             TEXT,
  description         TEXT,
  status              TEXT,
  date_submitted      DATE,
  neighbourhood_id    INT REFERENCES neighbourhoods(id),
  geom                GEOMETRY(Point, 4326)
);

-- Public comments on applications. For now only planning staff's summaries of
-- what residents raised at community consultation; residents' own letters may
-- follow (source = 'letter'), de-identified before they are stored.
CREATE TABLE comments (
  id                  TEXT PRIMARY KEY,       -- e.g. 'staff:2024/sc/244240:3'
  source              TEXT NOT NULL,          -- staff_report, letter
  source_url          TEXT NOT NULL,
  application_number  TEXT,                   -- not a foreign key: some reports
                                              -- predate the open dataset's rows
  report_title        TEXT,
  report_date         DATE,
  text                TEXT NOT NULL,
  neighbourhood_id    INT REFERENCES neighbourhoods(id),
  geom                GEOMETRY(Point, 4326),
  embedding           vector(384),            -- bge-small-en-v1.5, for retrieval
  embedding_model     TEXT,                   -- which model made the vector
  themes              TEXT[],                 -- same theme names as persona reactions
  stance              TEXT,                   -- concern, support, mixed
  tagged_by           TEXT                    -- which model wrote themes and stance
);

-- Named OpenStreetMap features that are notable: a Wikidata link, a capacity, or
-- a heritage or historic tag. Wikidata columns are filled only when the pipeline
-- has a contact for Wikimedia's robot policy (WIKIDATA_CONTACT).
CREATE TABLE landmarks (
  fid               TEXT PRIMARY KEY,         -- 'osm:w7969701'
  name              TEXT NOT NULL,
  kind              TEXT,                     -- OSM category, e.g. stadium, museum
  wikidata          TEXT,                     -- e.g. 'Q1124'
  osm_capacity      INT,
  osm_opened        TEXT,
  osm_heritage      TEXT,
  wd_description    TEXT,
  wd_opened         INT,
  wd_capacity       INT,
  wd_heritage       TEXT[],
  geom              GEOMETRY(Geometry, 4326) NOT NULL
);

-- Toronto Heritage Register: listed and designated properties (address points).
CREATE TABLE heritage_properties (
  id                INT PRIMARY KEY,
  address           TEXT,
  status            TEXT,                     -- 'Part IV', 'Part V', 'Listed'
  district          TEXT,
  built             TEXT,
  architect         TEXT,
  description       TEXT,
  geom              GEOMETRY(Point, 4326) NOT NULL
);

-- =========================================================
-- 5. EVALUATION
-- =========================================================

CREATE TABLE eval_runs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  application_number  TEXT REFERENCES applications(application_number),
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
CREATE INDEX ON applications          USING GIST (geom);
CREATE INDEX ON comments              USING GIST (geom);
CREATE INDEX ON landmarks             USING GIST (geom);
CREATE INDEX ON heritage_properties   USING GIST (geom);

CREATE INDEX ON personas (neighbourhood_id);
CREATE INDEX ON persona_reactions (proposal_id);
CREATE INDEX ON applications (neighbourhood_id);
CREATE INDEX ON comments (neighbourhood_id);
CREATE INDEX ON comments (application_number);
CREATE INDEX ON comments USING hnsw (embedding vector_cosine_ops);