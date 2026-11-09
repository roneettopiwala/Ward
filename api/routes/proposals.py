import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sse_starlette import EventSourceResponse

from routes.features import Conn
from services import proposals
from services.analysis import analyze
from services.catalog import TypeDef, catalog
from services.facts import ProposalInput

router = APIRouter(tags=["proposals"])


class ProposalCreated(BaseModel):
    id: uuid.UUID
    status: str


@router.get("/catalog")
async def get_catalog() -> list[TypeDef]:
    return list(catalog().values())


@router.post("/proposals", status_code=201)
async def create_proposal(conn: Conn, body: ProposalInput) -> ProposalCreated:
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
