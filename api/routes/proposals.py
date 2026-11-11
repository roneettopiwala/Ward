import json
import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sse_starlette import EventSourceResponse

from routes.features import Conn
from services import llm, parse, proposals
from services.analysis import analyze
from services.catalog import TypeDef, catalog

log = logging.getLogger(__name__)

router = APIRouter(tags=["proposals"])


class ProposalCreated(BaseModel):
    id: uuid.UUID
    status: str


@router.get("/catalog")
async def get_catalog() -> list[TypeDef]:
    return list(catalog().values())


@router.post("/proposals/parse")
async def parse_prompt(body: parse.ParseRequest) -> parse.ParseResult:
    """A typed prompt (and the current proposal, for follow-ups) as catalog parts."""
    try:
        return await parse.parse(body)
    except llm.LLMError as e:
        raise HTTPException(
            422, "Couldn't turn that into a proposal. Try describing it differently."
        ) from e
    except Exception as e:
        # Network, key or provider errors: answer cleanly so the browser shows a
        # message (an unhandled 500 carries no CORS headers and looks like a CORS error).
        log.exception("prompt parsing failed")
        raise HTTPException(503, llm.friendly_error(e)) from e


@router.post("/proposals", status_code=201)
async def create_proposal(conn: Conn, body: proposals.ProposalCreate) -> ProposalCreated:
    """Validate and store a proposal. Analysis streams from /proposals/{id}/events."""
    try:
        new_id = await proposals.create(conn, body)
    except proposals.ProposalError as e:
        raise HTTPException(422, str(e)) from e
    return ProposalCreated(id=new_id, status="draft")


@router.get("/proposals/{proposal_id}")
async def get_proposal(conn: Conn, proposal_id: uuid.UUID) -> proposals.StoredProposal:
    stored = await proposals.get(conn, proposal_id)
    if stored is None:
        raise HTTPException(404, "not_found")
    return stored


@router.get("/proposals/{proposal_id}/events")
async def proposal_events(request: Request, proposal_id: uuid.UUID) -> EventSourceResponse:
    """Server-sent events: status, fact_sheet, pros_cons, then done or error."""

    async def stream() -> AsyncIterator[dict[str, str]]:
        async for e in analyze(request.app.state.engine, request.app.state.redis, proposal_id):
            yield {"event": e.event, "data": json.dumps(e.data)}

    return EventSourceResponse(stream())
