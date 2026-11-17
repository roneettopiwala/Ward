"""Comment retrieval: what real residents nearby have said about similar proposals.

Each persona gets up to three comments from past consultations, as references
for what people notice and how they argue, never as their opinion. The search
text is the proposal plus what that persona cares about, so neighbours reacting
to the same proposal see different comments.

Comments must be relevant to the proposal (in the top quarter of all comments
for it). Among those, each persona's are ranked by relevance to the proposal and
to what they care about, with a bonus for their own neighbourhood and a smaller
one for comments within a few kilometres of home, so local voices win when they
fit and comments from elsewhere fill in. A comment already given to another
persona ranks a little lower, so neighbours don't all see the same three.

Comments are embedded offline by the pipeline (`--only embeddings`); queries
here use the same local model, loaded on first use.
"""

import asyncio
import re
import threading
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from services.facts import FactSheet
from services.personas import Persona

if TYPE_CHECKING:
    from fastembed import TextEmbedding

MODEL = "BAAI/bge-small-en-v1.5"
"""Must match pipeline/ward_pipeline/sources/embeddings.py."""
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "fastembed"
PER_PERSONA = 3
RELEVANT_SHARE = 0.25
"""Only comments in this top share of similarity to the proposal can be used."""
NEARBY_M = 3000
LOCAL_BONUS = 0.10
NEARBY_BONUS = 0.05
REPEAT_PENALTY = 0.03
"""Per persona already given the comment. Similarities differ by a few hundredths."""
CANDIDATES = 30
COPY_WORDS = 6
"""A quote sharing this many words in a row with a reference counts as copying."""

_model: "TextEmbedding | None" = None
_model_lock = threading.Lock()


class Reference(BaseModel):
    id: str
    text: str
    stance: str | None
    where: str
    """"your neighbourhood", "nearby" or "elsewhere in Toronto"."""


def _embedder() -> "TextEmbedding":
    # Imported here: loading the model takes a second, and only analysis needs it.
    global _model
    with _model_lock:
        if _model is None:
            from fastembed import TextEmbedding

            _model = TextEmbedding(MODEL, cache_dir=str(CACHE_DIR))
        return _model


def _embed(texts: list[str]) -> list[str]:
    vectors = _embedder().embed([QUERY_PREFIX + t for t in texts])
    return ["[" + ",".join(f"{x:.6f}" for x in v) + "]" for v in vectors]


def _proposal_text(sheet: FactSheet) -> str:
    return f"A proposed {sheet.type_label}."


def _persona_text(p: Persona) -> str:
    cares = ", ".join(p.values) if p.values else "my everyday life"
    commute = f" I usually get around by {p.commute_mode}." if p.commute_mode else ""
    return f"What matters to me: {cares}.{commute}"


async def for_personas(
    conn: AsyncConnection, personas: list[Persona], sheet: FactSheet
) -> dict[uuid.UUID, list[Reference]]:
    """Up to PER_PERSONA references for each persona, keyed by persona id."""
    if not personas:
        return {}
    have = await conn.scalar(
        text("SELECT count(*) FROM comments WHERE embedding_model = :m"), {"m": MODEL}
    )
    if not have:
        return {p.id: [] for p in personas}
    vectors = await asyncio.to_thread(
        _embed, [_proposal_text(sheet), *(_persona_text(p) for p in personas)]
    )
    proposal_vec, persona_vecs = vectors[0], vectors[1:]
    cutoff = await conn.scalar(
        text(
            "SELECT percentile_cont(:q) WITHIN GROUP "
            "(ORDER BY 1 - (embedding <=> CAST(:v AS vector))) "
            "FROM comments WHERE embedding_model = :m"
        ),
        {"q": 1 - RELEVANT_SHARE, "v": proposal_vec, "m": MODEL},
    )
    found: dict[uuid.UUID, list[Reference]] = {}
    used: dict[str, int] = {}
    for p, vec in zip(personas, persona_vecs, strict=True):
        rows = (
            await conn.execute(
                text(
                    """
                    WITH scored AS (
                      SELECT id, text, stance,
                             1 - (embedding <=> CAST(:pv AS vector)) AS fit,
                             1 - (embedding <=> CAST(:qv AS vector)) AS mine,
                             CASE WHEN neighbourhood_id = :nid THEN 0
                                  WHEN ST_DWithin(geom::geography,
                                       ST_SetSRID(ST_MakePoint(:x, :y), 4326)::geography,
                                       :near) THEN 1
                                  ELSE 2 END AS tier
                      FROM comments WHERE embedding_model = :m
                    )
                    SELECT id, text, stance, tier,
                           fit + mine + CASE tier WHEN 0 THEN CAST(:local AS float8)
                                                  WHEN 1 THEN CAST(:nearby AS float8)
                                                  ELSE 0.0 END AS score
                    FROM scored
                    WHERE fit >= CAST(:cutoff AS float8)
                    ORDER BY score DESC
                    LIMIT :n
                    """
                ),
                {
                    "pv": proposal_vec,
                    "qv": vec,
                    "m": MODEL,
                    "nid": p.neighbourhood_id,
                    "x": p.home[0],
                    "y": p.home[1],
                    "near": NEARBY_M,
                    "local": LOCAL_BONUS,
                    "nearby": NEARBY_BONUS,
                    "cutoff": cutoff,
                    "n": CANDIDATES,
                },
            )
        ).all()
        ranked = sorted(rows, key=lambda r: r.score - REPEAT_PENALTY * used.get(r.id, 0),
                        reverse=True)  # fmt: skip
        picked: list[Reference] = []
        seen: set[str] = set()
        for r in ranked:
            key = _words(r.text)
            if key in seen:
                continue
            seen.add(key)
            where = ("your neighbourhood", "nearby", "elsewhere in Toronto")[r.tier]
            picked.append(Reference(id=r.id, text=r.text, stance=r.stance, where=where))
            used[r.id] = used.get(r.id, 0) + 1
            if len(picked) == PER_PERSONA:
                break
        found[p.id] = picked
    return found


def _words(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", s.lower()))


def copied(quote: str, references: list[Reference]) -> str | None:
    """The first run of COPY_WORDS words the quote shares with a reference, if any."""
    words = _words(quote).split()
    runs = {" ".join(words[i : i + COPY_WORDS]) for i in range(len(words) - COPY_WORDS + 1)}
    for ref in references:
        padded = f" {_words(ref.text)} "
        for run in runs:
            if f" {run} " in padded:
                return run
    return None
