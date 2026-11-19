-- Phase 7: regenerated personas replace old ones. Old personas are retired, not
-- deleted, so past proposals keep their reactions (persona_reactions points at them).

ALTER TABLE personas ADD COLUMN retired_at TIMESTAMPTZ;
CREATE INDEX ON personas (neighbourhood_id) WHERE retired_at IS NULL;
