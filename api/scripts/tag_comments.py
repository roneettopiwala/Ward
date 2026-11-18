"""Tag residents' comments with themes and a stance, using the parse model (Haiku).

    cd api && .venv/bin/python -m scripts.tag_comments [--all]

Only comments without tags are sent unless --all. Twenty per call, a few calls
at a time; a batch that fails validation twice is logged and left for a rerun.
"""

import argparse
import asyncio
import json
import logging
from typing import Literal, get_args

from pydantic import BaseModel, Field
from sqlalchemy import text

from db import create_engine
from services import llm
from services.reactions import Theme
from settings import get_settings

log = logging.getLogger("tag_comments")

BATCH = 20
PARALLEL = 4


class Tag(BaseModel):
    id: str
    themes: list[Theme] = Field(min_length=1, max_length=3)
    stance: Literal["concern", "support", "mixed"]


class Tags(BaseModel):
    tags: list[Tag]


def _problems(tags: Tags, ids: list[str]) -> list[str]:
    got = [t.id for t in tags.tags]
    found = []
    if missing := sorted(set(ids) - set(got)):
        found.append(f"no tags for ids {missing}; tag every comment")
    if extra := sorted(set(got) - set(ids)):
        found.append(f"unknown ids {extra}; use the ids you were given")
    if len(got) != len(set(got)):
        found.append("some ids are tagged more than once; tag each once")
    return found


async def main(retag: bool) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    model = get_settings().parse_model
    system = llm.prompt("comment_tag").replace("{themes}", ", ".join(get_args(Theme)))
    engine = create_engine()
    where = "" if retag else "WHERE themes IS NULL"
    async with engine.connect() as conn:
        query = text(f"SELECT id, text FROM comments {where} ORDER BY id")
        rows = (await conn.execute(query)).all()
    batches = [rows[i : i + BATCH] for i in range(0, len(rows), BATCH)]
    log.info("%d comments to tag in %d calls with %s", len(rows), len(batches), model)
    gate = asyncio.Semaphore(PARALLEL)
    failed = 0

    async def one(batch: list) -> None:
        nonlocal failed
        ids = [r.id for r in batch]
        user = json.dumps({"comments": [{"id": r.id, "text": r.text} for r in batch]}, indent=1)
        async with gate:
            try:
                tags, used = await llm.complete_json(
                    system, user, Tags, check=lambda t: _problems(t, ids), model=model,
                    max_tokens=4000,
                )  # fmt: skip
            except llm.LLMError:
                log.warning("a batch starting at %s failed twice; rerun to retry it", ids[0])
                failed += 1
                return
        async with engine.begin() as conn:
            for t in tags.tags:
                await conn.execute(
                    text(
                        "UPDATE comments SET themes = :themes, stance = :stance, tagged_by = :m "
                        "WHERE id = :id"
                    ),
                    {"themes": list(t.themes), "stance": t.stance, "m": used, "id": t.id},
                )

    await asyncio.gather(*(one(b) for b in batches))
    await engine.dispose()
    log.info("done: %d of %d batches failed", failed, len(batches))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="retag comments that have tags")
    asyncio.run(main(parser.parse_args().all))
