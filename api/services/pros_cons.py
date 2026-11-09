"""Pros and cons: the LLM phrases fact sheet values, and every claim is checked against them."""

import json
import re

from pydantic import BaseModel, Field

from services import llm
from services.facts import FactSheet

# Numbers as written in text: 1,234 / 4.5 / 28
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


class Point(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    facts: list[str] = Field(min_length=1)
    """Ids of the fact sheet entries this claim rests on."""


class ProsCons(BaseModel):
    pros: list[Point] = Field(min_length=1, max_length=4)
    cons: list[Point] = Field(min_length=1, max_length=4)


class SourcedPoint(Point):
    sources: list[str]
    """Where the cited facts come from, for the SOURCE line."""


class ProsConsResult(BaseModel):
    pros: list[SourcedPoint]
    cons: list[SourcedPoint]
    model: str


async def generate(sheet: FactSheet, model: str | None = None) -> ProsConsResult:
    payload = {
        "proposal": {
            "type": sheet.type_label,
            "site": sheet.site_name,
            "impact_radius_m": sheet.impact_radius_m,
        },
        "facts": [f.model_dump(include={"id", "label", "display", "source"}) for f in sheet.facts],
    }
    result, used = await llm.complete_json(
        system=llm.prompt("pros_cons"),
        user=json.dumps(payload, ensure_ascii=False, indent=1),
        schema=ProsCons,
        check=lambda r: problems(r, sheet),
        model=model,
    )
    facts = sheet.by_id()

    def sourced(p: Point) -> SourcedPoint:
        sources = list(dict.fromkeys(facts[i].source for i in p.facts))
        return SourcedPoint(text=p.text, facts=p.facts, sources=sources)

    return ProsConsResult(
        pros=[sourced(p) for p in result.pros],
        cons=[sourced(p) for p in result.cons],
        model=used,
    )


def problems(result: ProsCons, sheet: FactSheet) -> list[str]:
    """Claims that cite unknown facts or use numbers their facts don't contain."""
    facts = sheet.by_id()
    found: list[str] = []
    for kind, points in (("pro", result.pros), ("con", result.cons)):
        for p in points:
            unknown = [i for i in p.facts if i not in facts]
            if unknown:
                found.append(f'{kind} "{p.text}" cites unknown fact ids {unknown}')
                continue
            cited = " ".join(
                f"{facts[i].label} {facts[i].display} {facts[i].source}" for i in p.facts
            )
            # The impact radius is given with the proposal, so it may be quoted too.
            allowed = {*_numbers(cited), sheet.impact_radius_m}
            stray = [n for n in _numbers(p.text) if n not in allowed]
            if stray:
                found.append(
                    f'{kind} "{p.text}" uses numbers {stray} that are not in the cited facts '
                    f"{p.facts}; quote cited facts exactly or cite the fact that has the number"
                )
    return found


def _numbers(text: str) -> list[float]:
    return [float(n.replace(",", "")) for n in NUMBER.findall(text)]
