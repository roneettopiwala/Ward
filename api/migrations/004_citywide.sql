-- Phase 6: citywide data. Streets with a pgRouting graph, the cycling network,
-- and a log of which neighbourhoods the ingest has finished.

CREATE EXTENSION IF NOT EXISTS pgrouting;

CREATE TABLE streets (
  fid         TEXT PRIMARY KEY,               -- 'street:<centreline id>'
  name        TEXT,
  road_class  TEXT,                           -- expressway, ramp (expressway ramp), arterial_ramp,
                                              -- major_arterial, minor_arterial,
                                              -- collector, local, laneway, access, busway,
                                              -- trail, walkway
  source      BIGINT,                         -- pgRouting graph nodes (City intersection ids)
  target      BIGINT,
  length_m    REAL,
  geom        GEOMETRY(LineString, 4326) NOT NULL
);

CREATE TABLE cycling (
  fid            TEXT PRIMARY KEY,            -- 'cycling:<segment id>'
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

CREATE INDEX ON streets USING GIST (geom);
CREATE INDEX ON streets (source);
CREATE INDEX ON streets (target);
CREATE INDEX ON streets (road_class);
CREATE INDEX ON cycling USING GIST (geom);
