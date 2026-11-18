-- Phase 7: the neighbourhood context cards a proposal's analysis used, so a
-- reopened proposal (and Phase 8 eval) sees exactly what personas were given.

ALTER TABLE proposals ADD COLUMN context JSONB;  -- [ContextCard, ...], most affected first
