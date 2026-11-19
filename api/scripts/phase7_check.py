"""Phase 7 done-when check: the same proposal in two neighbourhoods.

    cd api && .venv/bin/python -m scripts.phase7_check [--a 142] [--b 165] [--label before]

Phase 7 is done when "the same proposal type in two different neighbourhoods
produces clearly different, locally grounded reactions, and personas reacting
to the same proposal sound like different people". This runs a 12-storey condo
on a similar-sized lot in each neighbourhood through the full analysis, then
measures:

- different: quotes are more alike within a neighbourhood than across the two
  (local embeddings), and the top themes differ;
- locally grounded: share of quotes that name one of the persona's own places,
  their neighbourhood, or something from its context card;
- different people: how alike quotes are within one proposal, how many distinct
  openings there are, and the spread of quote lengths.

Prints a report with sample quotes and saves the numbers as JSON in
api/.cache/phase7_check/ for later comparison (Phase 8). Uses the LLM: about
30 reactions plus pros and cons.
"""

import argparse
import asyncio
import json
import re
import statistics
import uuid
from collections import Counter
from datetime import datetime
from itertools import combinations
from pathlib import Path

import numpy as np
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from db import create_engine, create_redis
from services import retrieval
from services.analysis import analyze

OUT_DIR = Path(__file__).resolve().parent.parent / ".cache" / "phase7_check"
PARAMS = {"height_m": 38.4, "units": 150}  # 12 storeys
LOT_M2 = (2500, 6000)
# Provisional bars; Phase 8 sets real ones.
GROUNDED_MIN = 0.5
OPENINGS_MIN = 0.8


async def _lot(conn: AsyncConnection, nid: int) -> tuple[str, str]:
    row = (
        await conn.execute(
            text(
                """
                SELECT pa.fid, ST_AsGeoJSON(pa.geom) AS g FROM parcels pa
                JOIN neighbourhoods n ON n.id = :nid AND ST_Contains(n.geom, pa.geom)
                WHERE pa.area_m2 BETWEEN :lo AND :hi
                ORDER BY pa.fid LIMIT 1
                """
            ),
            {"nid": nid, "lo": LOT_M2[0], "hi": LOT_M2[1]},
        )
    ).one()
    return row.fid, row.g


async def _run(engine: AsyncEngine, redis: Redis, nid: int) -> dict:
    async with engine.begin() as conn:
        fid, geometry = await _lot(conn, nid)
        name = await conn.scalar(text("SELECT name FROM neighbourhoods WHERE id = :n"), {"n": nid})
        pid = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO proposals (id, session_id, prompt, type, params, replaces, geom, "
                "status) VALUES (:id, 'phase7-check', '12-storey condo', 'condo', "
                "CAST(:p AS jsonb), ARRAY[:fid], ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326), "
                "'draft')"
            ),
            {"id": pid, "p": json.dumps(PARAMS), "fid": fid, "g": geometry},
        )
    async for event in analyze(engine, redis, pid):
        if event.event == "error":
            raise RuntimeError(f"{name}: {event.data}")
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT p.name, p.role, r.stance, r.quote, r.raw->'output'->'themes' AS themes,
                           COALESCE((SELECT array_agg(x->>'name') FROM jsonb_array_elements(
                               r.raw->'impact'->'places') x), '{}') AS places,
                           n.name AS home
                    FROM persona_reactions r JOIN personas p ON p.id = r.persona_id
                    JOIN neighbourhoods n ON n.id = p.neighbourhood_id
                    WHERE r.proposal_id = :id ORDER BY r.stance
                    """
                ),
                {"id": pid},
            )
        ).all()
        stored = (
            await conn.execute(
                text("SELECT context, fact_sheet FROM proposals WHERE id = :id"), {"id": pid}
            )
        ).one()
    facts = [f["display"] for f in (stored.fact_sheet or {}).get("facts", [])]
    return {"neighbourhood": name, "proposal_id": str(pid), "lot": fid,
            "context": stored.context or [], "facts": facts,
            "reactions": [dict(r._mapping) for r in rows]}  # fmt: skip


# Capitalised names in a quote ("Lusted Park", "Union Station", "Finch").
NAME = re.compile(r"(?<![.!?] )(?<!^)\b[A-Z][\w'’.-]+(?: [A-Z][\w'’.-]+)*")
NOT_NAMES = {"I", "I'm", "I'd", "I've", "I'll", "It's", "Twelve", "The"}


def _local_text(side: dict) -> str:
    """Everything local the personas were given: context cards and the fact sheet."""
    return (json.dumps(side["context"]) + " " + " ".join(side.get("facts", []))).lower()


def _grounded(r: dict, local: str) -> bool:
    """The quote names something real and local: one of the persona's places, their
    neighbourhood, or a place in the context card or fact sheet."""
    quote = r["quote"].lower()
    own = {n.lower() for n in r["places"] if n} | {r["home"].lower()}
    if any(n in quote for n in own if len(n) > 3):
        return True
    names = [n for n in NAME.findall(r["quote"]) if n not in NOT_NAMES and len(n) > 3]
    return any(n.lower() in local for n in names)


def _mean_sim(vectors: np.ndarray, pairs: list[tuple[int, int]]) -> float:
    return float(np.mean([vectors[i] @ vectors[j] for i, j in pairs])) if pairs else 0.0


def _opening(quote: str) -> str:
    return " ".join(quote.lower().split()[:3])


def measure(a: dict, b: dict) -> dict:
    quotes = [r["quote"] for r in a["reactions"]] + [r["quote"] for r in b["reactions"]]
    vectors = np.array(list(retrieval._embedder().embed(quotes)))
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    na = len(a["reactions"])
    ia, ib = range(na), range(na, len(quotes))
    within_a = _mean_sim(vectors, list(combinations(ia, 2)))
    within_b = _mean_sim(vectors, list(combinations(ib, 2)))
    across = _mean_sim(vectors, [(i, j) for i in ia for j in ib])

    def side(s: dict, within: float) -> dict:
        rs = s["reactions"]
        local = _local_text(s)
        themes = Counter(t for r in rs for t in (r["themes"] or []))
        lengths = [len(r["quote"].split()) for r in rs]
        return {
            "neighbourhood": s["neighbourhood"],
            "reactions": len(rs),
            "mean_stance": round(statistics.mean(r["stance"] for r in rs), 2),
            "top_themes": [t for t, _ in themes.most_common(3)],
            "grounded": round(sum(_grounded(r, local) for r in rs) / len(rs), 2),
            "distinct_openings": round(len({_opening(r["quote"]) for r in rs}) / len(rs), 2),
            "quote_similarity": round(within, 3),
            "words_min_max_sd": [min(lengths), max(lengths), round(statistics.pstdev(lengths), 1)],
        }

    sa, sb = side(a, within_a), side(b, within_b)
    overlap = len(set(sa["top_themes"]) & set(sb["top_themes"]))
    return {
        "a": sa,
        "b": sb,
        "across_similarity": round(across, 3),
        "separation": round((within_a + within_b) / 2 - across, 3),
        "top_theme_overlap": f"{overlap} of 3",
    }


def report(m: dict, a: dict, b: dict) -> str:
    def mark(ok: bool) -> str:
        return "pass" if ok else "CHECK"

    lines = ["Phase 7 done-when check", ""]
    for key, s in (("a", a), ("b", b)):
        x = m[key]
        lines += [
            f"## {x['neighbourhood']}  ({x['reactions']} reactions, "
            f"mean stance {x['mean_stance']})",
            f"  top themes:          {', '.join(x['top_themes'])}",
            f"  locally grounded:    {x['grounded']:.0%}  [{mark(x['grounded'] >= GROUNDED_MIN)}]",
            f"  distinct openings:   {x['distinct_openings']:.0%}  "
            f"[{mark(x['distinct_openings'] >= OPENINGS_MIN)}]",
            f"  quote similarity:    {x['quote_similarity']}  (lower = more varied)",
            f"  words min/max/sd:    {x['words_min_max_sd']}",
            "  sample quotes:",
        ]
        rs = s["reactions"]
        for r in (rs[0], rs[len(rs) // 2], rs[-1]):
            lines.append(f'    {r["name"]} ({r["stance"]:+.1f}): "{r["quote"]}"')
        lines.append("")
    lines += [
        "## Between the two",
        f"  similarity across:   {m['across_similarity']}",
        f"  separation:          {m['separation']}  (within minus across; above 0 = the "
        f"neighbourhoods sound different)  [{mark(m['separation'] > 0)}]",
        f"  top theme overlap:   {m['top_theme_overlap']}",
    ]
    return "\n".join(lines)


async def remeasure(saved: dict) -> dict:
    """Score a saved run again (e.g. after changing a metric), without the LLM."""
    a, b = saved["runs"]
    engine = create_engine()
    async with engine.connect() as conn:
        for run in (a, b):
            if "facts" not in run:
                sheet = await conn.scalar(
                    text("SELECT fact_sheet FROM proposals WHERE id = :id"),
                    {"id": run["proposal_id"]},
                )
                run["facts"] = [f["display"] for f in (sheet or {}).get("facts", [])]
    await engine.dispose()
    m = measure(a, b)
    print(report(m, a, b))
    return {**saved, "metrics": m, "runs": [a, b]}


async def main(a_id: int, b_id: int, label: str) -> None:
    engine, redis = create_engine(), create_redis()
    try:
        a = await _run(engine, redis, a_id)
        b = await _run(engine, redis, b_id)
    finally:
        await redis.aclose()
        await engine.dispose()
    m = measure(a, b)
    print(report(m, a, b))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{label}.json"
    path.write_text(json.dumps({"label": label, "metrics": m, "runs": [a, b]}, indent=1,
                               default=str))  # fmt: skip
    print(f"\nsaved {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a", type=int, default=142, help="neighbourhood (default Woburn North)")
    parser.add_argument("--b", type=int, default=165, help="neighbourhood (default Harbourfront)")
    parser.add_argument("--label", default="run")
    parser.add_argument("--remeasure", type=Path, help="score a saved run again, no LLM")
    args = parser.parse_args()
    if args.remeasure:
        rescored = asyncio.run(remeasure(json.loads(args.remeasure.read_text())))
        args.remeasure.write_text(json.dumps(rescored, indent=1, default=str))
    else:
        asyncio.run(main(args.a, args.b, args.label))
