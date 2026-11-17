-- Phase 7: development applications and what residents said about them.

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
  geom                GEOMETRY(Point, 4326)
);

CREATE INDEX ON applications USING GIST (geom);
CREATE INDEX ON applications (neighbourhood_id);
CREATE INDEX ON comments USING GIST (geom);
CREATE INDEX ON comments (neighbourhood_id);
CREATE INDEX ON comments (application_number);
