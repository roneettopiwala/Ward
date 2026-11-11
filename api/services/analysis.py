"""The analysis pipeline: proposal -> fact sheet -> pros/cons + persona reactions.

A plain async generator over an engine and Redis, so scripts (Phase 8 eval)
can run it without the web app: `async for event in analyze(engine, redis, id)`.

After the fact sheet, pros/cons and persona reactions run at the same time;
their events are merged into one stream in the order they happen.
"""

import asyncio
import hashlib
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from services import impact, llm, personas, proposals, reactions
from services.catalog import Stack
from services.facts import FactSheet, ProposalInput, build_fact_sheet
from services.pros_cons import ProsConsResult, generate
from settings import get_settings

log = logging.getLogger(__name__)

CACHE_TTL_S = 7 * 24 * 3600
# Below this share of valid reactions, the persona step counts as failed.
MIN_REACTION_SHARE = 0.5


class AnalysisEvent(BaseModel):
    event: Literal[
        "status", "fact_sheet", "pros_cons", "personas", "persona", "sentiment", "done", "error"
    ]
    data: dict[str, Any]


Emit = Callable[[AnalysisEvent], Awaitable[None]]


class PersonaError(Exception):
    pass


def cache_key(proposal: ProposalInput) -> str:
    geometry = hashlib.sha256(json.dumps(proposal.geometry, sort_keys=True).encode()).hexdigest()
    key = json.dumps(
        {
            "parts": [part.model_dump() for part in proposal.parts()],
            "replaces": sorted(proposal.replaces),
            "geometry": geometry,
            "model": get_settings().llm_model,
        },
        sort_keys=True,
    )
    return "analysis:" + hashlib.sha256(key.encode()).hexdigest()


async def analyze(
    engine: AsyncEngine, redis: Redis, proposal_id: uuid.UUID
) -> AsyncIterator[AnalysisEvent]:
    async with engine.connect() as conn:
        stored = await proposals.get(conn, proposal_id)
        if stored is None:
            yield AnalysisEvent(event="error", data={"message": "proposal not found"})
            return
        cards = await proposals.reaction_cards(conn, proposal_id)
        if stored.status == "done" and stored.fact_sheet and stored.pros_cons and cards:
            async for e in _replay(stored.fact_sheet, stored.pros_cons, cards):
                yield e
            return

        await proposals.set_status(conn, proposal_id, "analyzing")
        yield AnalysisEvent(event="status", data={"status": "analyzing"})
        try:
            stack = Stack.of(stored.proposal.parts())
            key = cache_key(stored.proposal)
            cached = await redis.get(key)
            hit = json.loads(cached) if cached else None
            if hit:
                sheet = FactSheet.model_validate(hit["fact_sheet"])
            else:
                sheet = await build_fact_sheet(conn, stored.proposal)
            await proposals.save_fact_sheet(conn, proposal_id, sheet)
            yield _sheet_event(sheet)

            async def pros_cons(emit: Emit) -> None:
                if hit:
                    result = ProsConsResult.model_validate(hit["pros_cons"])
                else:
                    await emit(_status("writing pros and cons"))
                    result = await generate(sheet)
                    await redis.set(
                        key,
                        json.dumps(
                            {"fact_sheet": sheet.model_dump(), "pros_cons": result.model_dump()}
                        ),
                        ex=CACHE_TTL_S,
                    )
                async with engine.connect() as c:
                    await proposals.save_pros_cons(c, proposal_id, result)
                await emit(_pros_cons_event(result))

            async def persona_reactions(emit: Emit) -> None:
                await _personas(engine, proposal_id, stored.proposal, stack, sheet, emit)

            async for e in _merge(pros_cons, persona_reactions):
                yield e
            await proposals.set_status(conn, proposal_id, "done")
            yield AnalysisEvent(event="done", data={})
        except Exception as e:
            log.exception("analysis of %s failed", proposal_id)
            await conn.rollback()
            await proposals.set_status(conn, proposal_id, "failed")
            yield AnalysisEvent(event="error", data={"message": _message(e)})


async def _personas(
    engine: AsyncEngine,
    proposal_id: uuid.UUID,
    proposal: ProposalInput,
    stack: Stack,
    sheet: FactSheet,
    emit: Emit,
) -> None:
    async with engine.connect() as conn:
        nid = await personas.neighbourhood_of(conn, proposal.geometry)
    if nid is None:
        raise PersonaError("This site is outside the neighbourhoods Ward has data for.")
    async with engine.connect() as conn:
        ready = await personas.load(conn, nid)
    if not ready:
        await emit(_status("generating personas"))
        ready, _ = await personas.ensure(engine, nid)
    chosen = personas.select(ready, stack.relevant_to)

    async with engine.connect() as conn:
        impacts = await impact.compute(
            conn, chosen, proposal.geometry, proposal.replaces, stack.impact_radius_m
        )
        await proposals.clear_reactions(conn, proposal_id)
        await emit(AnalysisEvent(event="personas", data={"total": len(chosen)}))
        done: list[reactions.Reaction] = []
        async for p, r in reactions.react_all(chosen, impacts, sheet):
            if r is None:
                continue
            card = reactions.card(p, impacts[p.id], r)
            await proposals.save_reaction(
                conn,
                proposal_id,
                r.persona_id,
                r.model,
                r.reaction.stance,
                r.reaction.reasons,
                r.reaction.quote,
                {
                    "output": r.reaction.model_dump(),
                    "impact": impacts[p.id].model_dump(mode="json"),
                    "card": card,
                },
                r.latency_ms,
            )
            done.append(r.reaction)
            await emit(AnalysisEvent(event="persona", data=card))
    if len(done) < MIN_REACTION_SHARE * len(chosen):
        raise PersonaError(f"Only {len(done)} of {len(chosen)} personas gave a valid reaction.")
    await emit(AnalysisEvent(event="sentiment", data=reactions.sentiment(done).model_dump()))


async def _merge(*jobs: Callable[[Emit], Awaitable[None]]) -> AsyncIterator[AnalysisEvent]:
    """Run jobs concurrently and yield their events as they come. Re-raises a job's error."""
    queue: asyncio.Queue[AnalysisEvent | None] = asyncio.Queue()

    async def run(job: Callable[[Emit], Awaitable[None]]) -> None:
        try:
            await job(queue.put)
        finally:
            await queue.put(None)

    tasks = [asyncio.create_task(run(j)) for j in jobs]
    try:
        remaining = len(tasks)
        while remaining:
            item = await queue.get()
            if item is None:
                remaining -= 1
                # Fail fast: a finished job with an error stops the others.
                for t in tasks:
                    if t.done() and t.exception():
                        raise t.exception()  # type: ignore[misc]
                continue
            yield item
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _replay(
    sheet: FactSheet, result: ProsConsResult, cards: list[dict[str, Any]]
) -> AsyncIterator[AnalysisEvent]:
    yield AnalysisEvent(event="status", data={"status": "done", "cached": True})
    yield _sheet_event(sheet)
    yield _pros_cons_event(result)
    yield AnalysisEvent(event="personas", data={"total": len(cards)})
    for card in cards:
        yield AnalysisEvent(event="persona", data=card)
    done = [
        reactions.Reaction(
            stance=c["stance"], reasons=c["reasons"], quote=c["quote"], themes=c["themes"]
        )
        for c in cards
    ]
    yield AnalysisEvent(event="sentiment", data=reactions.sentiment(done).model_dump())
    yield AnalysisEvent(event="done", data={})


def _status(status: str) -> AnalysisEvent:
    return AnalysisEvent(event="status", data={"status": status})


def _sheet_event(sheet: FactSheet) -> AnalysisEvent:
    return AnalysisEvent(event="fact_sheet", data=sheet.model_dump())


def _pros_cons_event(result: ProsConsResult) -> AnalysisEvent:
    return AnalysisEvent(event="pros_cons", data=result.model_dump())


def _message(e: Exception) -> str:
    """Short, safe text for the panel; details stay in the server log."""
    name = type(e).__name__
    if isinstance(e, PersonaError):
        return str(e)
    if "LLMError" in name:
        return "A model's reply didn't pass validation, even after a retry."
    if type(e).__module__.startswith("litellm"):
        return llm.friendly_error(e)
    return "Analysis failed. See the API log for details."
