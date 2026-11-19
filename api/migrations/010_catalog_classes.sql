-- Phase 8: the catalog's six types become use classes with subtypes. Stored
-- proposals are rewritten so they still load and replay: every proposal gets
-- explicit components ({type: class, subtype, params, tags}), and fact sheets
-- name the class.

CREATE TEMP TABLE _type_map (old TEXT PRIMARY KEY, class TEXT NOT NULL, subtype TEXT NOT NULL)
  ON COMMIT DROP;
INSERT INTO _type_map VALUES
  ('condo', 'residential', 'condo_tower'),
  ('mall', 'retail', 'mall'),
  ('park', 'open_space', 'park'),
  ('community_garden', 'open_space', 'community_garden'),
  ('bike_lane', 'street', 'bike_lane'),
  ('transit_station', 'transit', 'station');

-- A part list with old type names rewritten (unknown names are left alone).
CREATE FUNCTION pg_temp.remap_parts(parts JSONB) RETURNS JSONB AS $$
  SELECT coalesce(jsonb_agg(
           CASE WHEN m.old IS NULL THEN e.part
                ELSE e.part || jsonb_build_object('type', m.class, 'subtype', m.subtype) END
           ORDER BY e.n), '[]'::jsonb)
  FROM jsonb_array_elements(parts) WITH ORDINALITY AS e(part, n)
  LEFT JOIN _type_map m ON m.old = e.part->>'type'
$$ LANGUAGE sql;

-- Single-part proposals had no components; give them one so the subtype survives.
UPDATE proposals
SET components = jsonb_build_array(
      jsonb_build_object('type', type, 'params', coalesce(params, '{}'::jsonb), 'tags', '[]'::jsonb))
WHERE components IS NULL OR jsonb_typeof(components) <> 'array'
   OR jsonb_array_length(components) = 0;

UPDATE proposals SET components = pg_temp.remap_parts(components);

UPDATE proposals p SET type = m.class FROM _type_map m WHERE p.type = m.old;

UPDATE proposals p
SET fact_sheet = jsonb_set(
      jsonb_set(p.fact_sheet, '{type}', to_jsonb(coalesce(m.class, p.fact_sheet->>'type'))),
      '{parts}', pg_temp.remap_parts(coalesce(p.fact_sheet->'parts', '[]'::jsonb)))
FROM (SELECT id, fact_sheet->>'type' AS old FROM proposals WHERE fact_sheet IS NOT NULL) f
LEFT JOIN _type_map m ON m.old = f.old
WHERE p.id = f.id;
