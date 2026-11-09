-- Phase 3: parks for green-space metrics, and proposals with their analysis.
-- Tables copied verbatim from docs/ward_schema.sql.

CREATE TABLE parks (
  fid       TEXT PRIMARY KEY,                 -- 'park:<id>'
  name      TEXT,
  area_m2   REAL,
  geom      GEOMETRY(MultiPolygon, 4326) NOT NULL
);

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

CREATE INDEX ON parks     USING GIST (geom);
CREATE INDEX ON proposals USING GIST (geom);
