"""Rebuild stored personas with the current generator.

    cd api && .venv/bin/python -m scripts.regenerate_personas [--only 142,165] [--force]

Every neighbourhood pool (and the citywide group) whose personas came from an
older generator is written again: same census-sampled facts, new stories,
voices and interests. Old personas are retired, not deleted, so past proposals
keep their reactions. Resumable: pools already on the current generator are
skipped unless --force. A few pools are generated at a time.
"""

import argparse
import asyncio
import logging

from sqlalchemy import text

from db import create_engine
from services import personas

log = logging.getLogger("regenerate_personas")

PARALLEL = 3


async def main(only: list[int] | None, force: bool) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    engine = create_engine()
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT CASE WHEN role = 'citywide' THEN NULL ELSE neighbourhood_id END AS nid,
                           bool_and(coalesce((traits->>'generator')::int, 1) >= :v) AS current
                    FROM personas WHERE retired_at IS NULL
                    GROUP BY 1 ORDER BY 1 NULLS LAST
                    """
                ),
                {"v": personas.GENERATOR_VERSION},
            )
        ).all()
    todo = [r.nid for r in rows if (force or not r.current) and (only is None or r.nid in only)]
    log.info("%d pools to regenerate, %d already current", len(todo), len(rows) - len(todo))
    gate = asyncio.Semaphore(PARALLEL)
    failed: list[int | None] = []

    async def one(nid: int | None) -> None:
        name = "citywide" if nid is None else f"neighbourhood {nid}"
        async with gate:
            try:
                n = await personas.regenerate(engine, nid)
                log.info("%s: %d personas", name, n)
            except Exception:
                log.exception("%s failed; rerun to retry it", name)
                failed.append(nid)

    await asyncio.gather(*(one(nid) for nid in todo))
    await engine.dispose()
    log.info("done: %d of %d failed", len(failed), len(todo))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="comma-separated neighbourhood numbers")
    parser.add_argument("--force", action="store_true", help="also redo current pools")
    args = parser.parse_args()
    only = [int(x) for x in args.only.split(",")] if args.only else None
    asyncio.run(main(only, args.force))
