"""Comment embeddings for retrieval, made locally (no API key).

Embeds every comment without a vector from the current model. The API embeds
its queries with the same model (api/services/retrieval.py), so the two must
change together; changing MODEL here re-embeds everything on the next run.
"""

import logging

from fastembed import TextEmbedding
from sqlalchemy import Engine, text

from ..config import CACHE_DIR

log = logging.getLogger(__name__)

MODEL = "BAAI/bge-small-en-v1.5"
BATCH = 256


def ingest(eng: Engine) -> int:
    with eng.connect() as conn:
        todo = conn.execute(
            text(
                "SELECT id, text FROM comments "
                "WHERE embedding IS NULL OR embedding_model IS DISTINCT FROM :m ORDER BY id"
            ),
            {"m": MODEL},
        ).all()
    if not todo:
        return 0
    log.info("embedding %d comments with %s", len(todo), MODEL)
    model = TextEmbedding(MODEL, cache_dir=str(CACHE_DIR / "fastembed"))
    vectors = model.embed([t for _, t in todo], batch_size=BATCH)
    with eng.begin() as conn:
        for (cid, _), v in zip(todo, vectors, strict=True):
            conn.execute(
                text(
                    "UPDATE comments SET embedding = CAST(:v AS vector), embedding_model = :m "
                    "WHERE id = :id"
                ),
                {"v": "[" + ",".join(f"{x:.6f}" for x in v) + "]", "m": MODEL, "id": cid},
            )
    return len(todo)
