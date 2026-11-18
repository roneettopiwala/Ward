-- Phase 7: landmark facts for the fact sheet, so replacing a stadium or a heritage
-- building says what it is, not just "a building used for recreation".

-- Named OpenStreetMap features that are notable: a Wikidata link, a capacity, or
-- a heritage or historic tag. Wikidata columns are filled from its public API.
CREATE TABLE landmarks (
  fid               TEXT PRIMARY KEY,         -- 'osm:w7969701' (OSM node/way/relation)
  name              TEXT NOT NULL,
  kind              TEXT,                     -- OSM category, e.g. stadium, museum
  wikidata          TEXT,                     -- e.g. 'Q1124'
  osm_capacity      INT,
  osm_opened        TEXT,                     -- OSM start_date as tagged
  osm_heritage      TEXT,
  wd_description    TEXT,                     -- e.g. 'multi-purpose stadium in Toronto'
  wd_opened         INT,                      -- year of official opening or inception
  wd_capacity       INT,
  wd_heritage       TEXT[],                   -- heritage designations, by label
  geom              GEOMETRY(Geometry, 4326) NOT NULL
);

-- Toronto Heritage Register: listed and designated properties (address points).
CREATE TABLE heritage_properties (
  id                INT PRIMARY KEY,          -- register OBJECTID
  address           TEXT,
  status            TEXT,                     -- 'Part IV', 'Part V', 'Listed'
  district          TEXT,                     -- Heritage Conservation District (Part V)
  built             TEXT,                     -- construction date as recorded
  architect         TEXT,
  description       TEXT,
  geom              GEOMETRY(Point, 4326) NOT NULL
);

CREATE INDEX ON landmarks USING GIST (geom);
CREATE INDEX ON heritage_properties USING GIST (geom);
