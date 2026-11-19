"""Prompt parsing: plain language -> a proposal's parts, validated against the catalog.

A fast model reads the selection, the catalog and the prompt (plus the current
proposal for follow-ups like "make it 2 storeys shorter") and replies with
parts. Heights may come as storeys; code converts them to metres with each
type's storey height, so the model never does unit arithmetic. Every part is
checked against the catalog, and the model gets one retry with the problems.
"""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from services import llm
from services.catalog import GEOMETRY_TYPES, GeometryKind, Param, Part, Stack, Subtype, catalog
from services.proposals import ProposalError, validate_parts
from settings import get_settings

SHAPE_NAMES: dict[GeometryKind, str] = {
    "polygon": "an area (a building, lot, park or drawn area)",
    "line": "a line drawn along streets",
    "point": "a point",
}


class Selection(BaseModel):
    """What the user selected, as the map knows it."""

    name: str | None = None
    use: str | None = None
    height_m: float | None = None
    footprint_m2: float | None = None
    lot_area_m2: float | None = None
    zoning: str | None = None


class ParseRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)
    geometry_type: str = "Polygon"
    selection: Selection = Selection()
    current: list[Part] | None = None
    """The proposal being refined, for follow-up prompts."""


class ParsedPart(BaseModel):
    # A param given beside "params" instead of inside it is an error the model can fix.
    model_config = ConfigDict(extra="forbid")

    type: str
    subtype: str | None = None
    params: dict[str, float] = {}
    storeys: float | None = Field(default=None, gt=0)
    """Height in storeys; converted to the type's height param in code."""
    tags: list[str] = Field(default=[], max_length=4)


class ParseReply(BaseModel):
    parts: list[ParsedPart] = Field(default=[], max_length=4)
    replaces_existing: bool = True
    assumptions: list[str] = Field(default=[], max_length=5)
    clarification: str | None = None


class ParseResult(BaseModel):
    parts: list[Part]
    """Empty when a clarification is needed."""
    replaces_existing: bool
    assumptions: list[str]
    clarification: str | None
    model: str


def _shape(geometry_type: str) -> GeometryKind:
    return next((k for k, ts in GEOMETRY_TYPES.items() if geometry_type in ts), "polygon")


def _params(params: dict[str, Param]) -> dict[str, Any]:
    return {
        name: {
            "label": p.label,
            "unit": p.unit,
            "default": p.default,
            "min": p.min,
            "max": p.max,
        }  # fmt: skip
        for name, p in params.items()
    }


def _subtype_brief(sub: Subtype) -> dict[str, Any]:
    out: dict[str, Any] = {"label": sub.label}
    if sub.description:
        out["description"] = sub.description
    if sub.params:
        out["extra_params"] = _params(sub.params)
    if sub.defaults:
        out["defaults"] = sub.defaults
    return out


def _catalog_brief(shape: GeometryKind) -> list[dict[str, Any]]:
    """The classes that fit the site's shape (an area, a line or a point)."""
    return [
        {
            "type": t.type,
            "label": t.label,
            "description": t.description,
            "kind": {"flat": "flat (no height)", "extrusion": "building"}.get(
                t.render.kind, t.render.kind
            ),
            "params": _params(t.params),
            "storey_height_m": t.storey_m,
            "height_param": t.render.height_param,
            "subtypes": {k: _subtype_brief(s) for k, s in t.subtypes.items()},
        }
        for t in catalog().values()
        if t.geometry == shape
    ]


def _current_brief(parts: list[Part]) -> list[dict[str, Any]]:
    """The current proposal, with storeys spelled out so follow-ups can adjust them."""
    stack = Stack.of(parts)
    out = []
    for part, t in stack.parts:
        entry: dict[str, Any] = part.model_dump(exclude_none=True)
        height = stack.part_height(part, t)
        if height and t.storey_m:
            entry["storeys"] = max(1, round(height / t.storey_m))
        out.append(entry)
    return out


def resolve(reply: ParseReply, geometry_type: str) -> tuple[list[Part], list[str]]:
    """The reply as catalog parts, and any problems to send back to the model."""
    if reply.clarification:
        return [], []
    if not reply.parts:
        return [], ["give at least one part, or a clarification question"]
    types = catalog()
    parts: list[Part] = []
    problems: list[str] = []
    for p in reply.parts:
        base = types.get(p.type)
        if base is None:
            problems.append(
                f"unknown type {p.type!r}; use one of the classes {sorted(types)} with a subtype"
            )
            continue
        subtype = base.normalise_subtype(p.subtype)
        t = base.resolve(subtype)
        params = dict(p.params)
        if p.storeys is not None:
            if not (t.render.height_param and t.storey_m):
                problems.append(f"{p.type} has no height; drop storeys")
                continue
            params[t.render.height_param] = round(p.storeys * t.storey_m, 1)
        parts.append(Part(type=p.type, subtype=subtype, params=params, tags=p.tags))
    if problems:
        return [], problems
    try:
        return validate_parts(parts, geometry_type), []
    except ProposalError as e:
        message = str(e)
        for t in types.values():
            hp = t.render.height_param
            if hp and t.storey_m and f"{t.type}: {hp}" in message:
                low, high = t.params[hp].min / t.storey_m, t.params[hp].max / t.storey_m
                message += f" (that is about {low:.0f} to {high:.0f} storeys)"
        return [], [message]


async def parse(req: ParseRequest) -> ParseResult:
    payload: dict[str, Any] = {
        "catalog": _catalog_brief(_shape(req.geometry_type)),
        "site_shape": SHAPE_NAMES[_shape(req.geometry_type)],
        "selection": req.selection.model_dump(exclude_none=True),
        "prompt": req.prompt,
    }
    if req.current:
        payload["current_proposal"] = _current_brief(req.current)

    def check(reply: ParseReply) -> list[str]:
        return resolve(reply, req.geometry_type)[1]

    reply, model = await llm.complete_json(
        system=llm.prompt("parse"),
        user=json.dumps(payload, ensure_ascii=False, indent=1),
        schema=ParseReply,
        check=check,
        model=get_settings().parse_model,
        max_tokens=1500,
    )
    parts, _ = resolve(reply, req.geometry_type)
    return ParseResult(
        parts=parts,
        replaces_existing=reply.replaces_existing,
        assumptions=reply.assumptions,
        clarification=reply.clarification if not parts else None,
        model=model,
    )
