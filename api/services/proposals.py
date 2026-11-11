"""Storing proposals. Creation takes the same structured object a parsed prompt will produce."""

import json
import uuid
from typing import Any

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from services.catalog import GEOMETRY_TYPES, Part, Stack, catalog
from services.facts import FactSheet, ProposalInput
from services.pros_cons import ProsConsResult


class ProposalError(ValueError):
    pass


MAX_PARTS = 4


class ProposalCreate(ProposalInput):
    """A new proposal, with where it came from."""

    prompt: str | None = None
    parent_id: uuid.UUID | None = None
    """The proposal this one refines."""


class StoredProposal(BaseModel):
    id: uuid.UUID
    status: str
    proposal: ProposalInput
    fact_sheet: FactSheet | None
    pros_cons: ProsConsResult | None


def validate_parts(parts: list[Part], geometry_type: str | None) -> list[Part]:
    """Parts with params resolved against the catalog. Raises ProposalError."""
    if not 1 <= len(parts) <= MAX_PARTS:
        raise ProposalError(f"a proposal has 1 to {MAX_PARTS} parts")
    out = []
    for i, part in enumerate(parts):
        typedef = catalog().get(part.type)
        if typedef is None:
            raise ProposalError(f"unknown type {part.type!r}")
        if geometry_type not in GEOMETRY_TYPES[typedef.geometry]:
            raise ProposalError(f"{part.type} needs {typedef.geometry} geometry")
        if typedef.render.kind == "flat" and len(parts) > 1 and i != len(parts) - 1:
            raise ProposalError(f"a {part.type} in a mixed-use proposal goes on the roof (last)")
        try:
            params = typedef.resolve_params(part.params)
        except ValueError as e:
            raise ProposalError(f"{part.type}: {e}") from e
        tags = [t.strip()[:40] for t in part.tags if t.strip()][:4]
        out.append(Part(type=part.type, params=params, tags=tags))
    return out


def validate[P: ProposalInput](raw: P) -> P:
    """The proposal with every part resolved; type/params become the main part's."""
    parts = validate_parts(raw.parts(), raw.geometry.get("type"))
    main, _ = Stack.of(parts).main
    plain = len(parts) == 1 and not parts[0].tags
    return raw.model_copy(
        update={"type": main.type, "params": main.params, "components": [] if plain else parts}
    )


async def create(conn: AsyncConnection, raw: ProposalCreate) -> uuid.UUID:
    proposal = validate(raw)
    geojson = json.dumps(proposal.geometry)
    valid = await conn.scalar(text("SELECT ST_IsValid(ST_GeomFromGeoJSON(:g))"), {"g": geojson})
    if not valid:
        raise ProposalError("geometry is not valid")
    new_id = await conn.scalar(
        text(
            """
            INSERT INTO proposals (type, params, components, replaces, geom, prompt, parent_id)
            VALUES (:type, CAST(:params AS jsonb), CAST(:components AS jsonb), :replaces,
                    ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326), :prompt, :parent)
            RETURNING id
            """
        ),
        {
            "type": proposal.type,
            "params": json.dumps(proposal.params),
            "components": json.dumps([c.model_dump() for c in proposal.components] or None),
            "replaces": proposal.replaces,
            "g": geojson,
            "prompt": proposal.prompt,
            "parent": proposal.parent_id,
        },
    )
    await conn.commit()
    return new_id


async def get(conn: AsyncConnection, proposal_id: uuid.UUID) -> StoredProposal | None:
    row = (
        await conn.execute(
            text(
                """
                SELECT p.id, p.status, p.type, p.params, p.components, p.replaces, p.fact_sheet,
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
            components=row.components or [],
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
