-- City data for Phase 2, copied from docs/ward_schema.sql.

CREATE TABLE neighbourhoods (
  id          INT PRIMARY KEY,               -- city's official neighbourhood number
  name        TEXT NOT NULL,
  geom        GEOMETRY(MultiPolygon, 4326) NOT NULL
);

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

CREATE INDEX ON neighbourhoods USING GIST (geom);
CREATE INDEX ON census_areas   USING GIST (geom);
CREATE INDEX ON buildings      USING GIST (geom);
CREATE INDEX ON parcels        USING GIST (geom);
CREATE INDEX ON zoning         USING GIST (geom);
CREATE INDEX ON transit_stops  USING GIST (geom);
CREATE INDEX ON pois           USING GIST (geom);
