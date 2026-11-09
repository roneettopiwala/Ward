"""The analysis pipeline: proposal -> fact sheet -> pros/cons, as a stream of events.

A plain async generator over an engine and Redis, so scripts (Phase 8 eval)
can run it without the web app: `async for event in analyze(engine, redis, id)`.
"""

import hashlib
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from services import proposals
from services.catalog import catalog
from services.facts import FactSheet, ProposalInput, build_fact_sheet
from services.pros_cons import ProsConsResult, generate
from settings import get_settings

log = logging.getLogger(__name__)

CACHE_TTL_S = 7 * 24 * 3600


class AnalysisEvent(BaseModel):
    event: Literal["status", "fact_sheet", "pros_cons", "done", "error"]
    data: dict[str, Any]


def cache_key(proposal: ProposalInput) -> str:
    geometry = hashlib.sha256(json.dumps(proposal.geometry, sort_keys=True).encode()).hexdigest()
    key = json.dumps(
        {
            "type": proposal.type,
            "params": proposal.params,
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
        if stored.status == "done" and stored.fact_sheet and stored.pros_cons:
            yield AnalysisEvent(event="status", data={"status": "done", "cached": True})
            yield _sheet_event(stored.fact_sheet)
            yield _pros_cons_event(stored.pros_cons)
            yield AnalysisEvent(event="done", data={})
            return

        await proposals.set_status(conn, proposal_id, "analyzing")
        yield AnalysisEvent(event="status", data={"status": "analyzing"})
        try:
            key = cache_key(stored.proposal)
            cached = await redis.get(key)
            if cached:
                hit = json.loads(cached)
                sheet = FactSheet.model_validate(hit["fact_sheet"])
                result = ProsConsResult.model_validate(hit["pros_cons"])
                await proposals.save_fact_sheet(conn, proposal_id, sheet)
                yield _sheet_event(sheet)
                await proposals.save_pros_cons(conn, proposal_id, result)
                yield _pros_cons_event(result)
            else:
                typedef = catalog()[stored.proposal.type]
                sheet = await build_fact_sheet(conn, stored.proposal, typedef)
                await proposals.save_fact_sheet(conn, proposal_id, sheet)
                yield _sheet_event(sheet)
                yield AnalysisEvent(event="status", data={"status": "writing pros and cons"})
                result = await generate(sheet)
                await proposals.save_pros_cons(conn, proposal_id, result)
                yield _pros_cons_event(result)
                await redis.set(
                    key,
                    json.dumps(
                        {"fact_sheet": sheet.model_dump(), "pros_cons": result.model_dump()}
                    ),
                    ex=CACHE_TTL_S,
                )
            await proposals.set_status(conn, proposal_id, "done")
            yield AnalysisEvent(event="done", data={})
        except Exception as e:
            log.exception("analysis of %s failed", proposal_id)
            await conn.rollback()
            await proposals.set_status(conn, proposal_id, "failed")
            yield AnalysisEvent(event="error", data={"message": _message(e)})


def _sheet_event(sheet: FactSheet) -> AnalysisEvent:
    return AnalysisEvent(event="fact_sheet", data=sheet.model_dump())


def _pros_cons_event(result: ProsConsResult) -> AnalysisEvent:
    return AnalysisEvent(event="pros_cons", data=result.model_dump())


def _message(e: Exception) -> str:
    """Short, safe text for the panel; details stay in the server log."""
    name = type(e).__name__
    if "AuthenticationError" in name:
        return "The LLM API key is missing or invalid (ANTHROPIC_API_KEY in api/.env)."
    if "LLMError" in name:
        return "The model's pros and cons didn't match the fact sheet, even after a retry."
    return "Analysis failed. See the API log for details."
