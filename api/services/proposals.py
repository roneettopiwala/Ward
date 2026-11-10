"""Storing proposals. Creation takes the same structured object a parsed prompt will produce."""

import json
import uuid
from typing import Any

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from services.catalog import GEOMETRY_TYPES, catalog
from services.facts import FactSheet, ProposalInput
from services.pros_cons import ProsConsResult


class ProposalError(ValueError):
    pass


class StoredProposal(BaseModel):
    id: uuid.UUID
    status: str
    proposal: ProposalInput
    fact_sheet: FactSheet | None
    pros_cons: ProsConsResult | None


def validate(raw: ProposalInput) -> ProposalInput:
    """The proposal with params resolved against the catalog. Raises ProposalError."""
    typedef = catalog().get(raw.type)
    if typedef is None:
        raise ProposalError(f"unknown type {raw.type!r}")
    if raw.geometry.get("type") not in GEOMETRY_TYPES[typedef.geometry]:
        raise ProposalError(f"{raw.type} needs {typedef.geometry} geometry")
    try:
        params = typedef.resolve_params(raw.params)
    except ValueError as e:
        raise ProposalError(str(e)) from e
    return raw.model_copy(update={"params": params})


async def create(conn: AsyncConnection, raw: ProposalInput) -> uuid.UUID:
    proposal = validate(raw)
    geojson = json.dumps(proposal.geometry)
    valid = await conn.scalar(text("SELECT ST_IsValid(ST_GeomFromGeoJSON(:g))"), {"g": geojson})
    if not valid:
        raise ProposalError("geometry is not valid")
    new_id = await conn.scalar(
        text(
            """
            INSERT INTO proposals (type, params, replaces, geom)
            VALUES (:type, CAST(:params AS jsonb), :replaces,
                    ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326))
            RETURNING id
            """
        ),
        {
            "type": proposal.type,
            "params": json.dumps(proposal.params),
            "replaces": proposal.replaces,
            "g": geojson,
        },
    )
    await conn.commit()
    return new_id


async def get(conn: AsyncConnection, proposal_id: uuid.UUID) -> StoredProposal | None:
    row = (
        await conn.execute(
            text(
                """
                SELECT p.id, p.status, p.type, p.params, p.replaces, p.fact_sheet,
                       ST_AsGeoJSON(p.geom) AS geometry, pc.pros, pc.cons, pc.model
                FROM proposals p LEFT JOIN pros_cons pc ON pc.proposal_id = p.id
                WHERE p.id = :id
                """
            ),
            {"id": proposal_id},
        )
    ).one_or_none()
    if row is None:
        return None
    pros_cons = (
        ProsConsResult(pros=row.pros, cons=row.cons, model=row.model)
        if row.pros is not None
        else None
    )
    return StoredProposal(
        id=row.id,
        status=row.status,
        proposal=ProposalInput(
            type=row.type,
            params=row.params or {},
            geometry=json.loads(row.geometry),
            replaces=row.replaces or [],
        ),
        fact_sheet=FactSheet.model_validate(row.fact_sheet) if row.fact_sheet else None,
        pros_cons=pros_cons,
    )


async def set_status(conn: AsyncConnection, proposal_id: uuid.UUID, status: str) -> None:
    await _write(conn, "UPDATE proposals SET status = :s WHERE id = :id", id=proposal_id, s=status)


async def save_fact_sheet(conn: AsyncConnection, proposal_id: uuid.UUID, sheet: FactSheet) -> None:
    await _write(
        conn,
        "UPDATE proposals SET fact_sheet = CAST(:f AS jsonb) WHERE id = :id",
        id=proposal_id,
        f=sheet.model_dump_json(),
    )


async def save_pros_cons(
    conn: AsyncConnection, proposal_id: uuid.UUID, result: ProsConsResult
) -> None:
    dumped = result.model_dump()
    await _write(
        conn,
        """
        INSERT INTO pros_cons (proposal_id, pros, cons, model)
        VALUES (:id, CAST(:pros AS jsonb), CAST(:cons AS jsonb), :model)
        ON CONFLICT (proposal_id) DO UPDATE
        SET pros = EXCLUDED.pros, cons = EXCLUDED.cons, model = EXCLUDED.model
        """,
        id=proposal_id,
        pros=json.dumps(dumped["pros"]),
        cons=json.dumps(dumped["cons"]),
        model=result.model,
    )


async def _write(conn: AsyncConnection, sql: str, **params: Any) -> None:
    await conn.execute(text(sql), params)
    await conn.commit()


async def save_reaction(
    conn: AsyncConnection,
    proposal_id: uuid.UUID,
    persona_id: str,
    model: str,
    stance: float,
    reasons: list[str],
    quote: str,
    raw: dict[str, Any],
    latency_ms: int,
) -> None:
    await _write(
        conn,
        """
        INSERT INTO persona_reactions
            (proposal_id, persona_id, model, stance, reasons, quote, raw, latency_ms)
        VALUES (:id, :persona, :model, :stance, :reasons, :quote, CAST(:raw AS jsonb), :latency)
        """,
        id=proposal_id,
        persona=uuid.UUID(persona_id),
        model=model,
        stance=stance,
        reasons=reasons,
        quote=quote,
        raw=json.dumps(raw),
        latency=latency_ms,
    )


async def clear_reactions(conn: AsyncConnection, proposal_id: uuid.UUID) -> None:
    await _write(conn, "DELETE FROM persona_reactions WHERE proposal_id = :id", id=proposal_id)


async def reaction_cards(conn: AsyncConnection, proposal_id: uuid.UUID) -> list[dict[str, Any]]:
    """The persona cards saved for a proposal, in the order they arrived."""
    rows = await conn.execute(
        text(
            "SELECT raw->'card' AS card FROM persona_reactions "
            "WHERE proposal_id = :id ORDER BY created_at, id"
        ),
        {"id": proposal_id},
    )
    return [r.card for r in rows if r.card]
