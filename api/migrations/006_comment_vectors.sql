-- Phase 7: comment embeddings (for retrieval) and theme/stance tags.

ALTER TABLE comments
  ADD COLUMN embedding        vector(384),     -- bge-small-en-v1.5, normalised
  ADD COLUMN embedding_model  TEXT,            -- which model made the vector
  ADD COLUMN themes           TEXT[],          -- same theme names as persona reactions
  ADD COLUMN stance           TEXT,            -- concern, support, mixed
  ADD COLUMN tagged_by        TEXT;            -- which model wrote themes and stance

CREATE INDEX ON comments USING hnsw (embedding vector_cosine_ops);
