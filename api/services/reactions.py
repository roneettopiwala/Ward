"""Persona reactions: each persona reads the fact sheet and their personal impact.

One fast model, called in parallel. Every reply is validated (stance range,
two reasons, a 1 to 3 sentence quote, known themes, no numbers that aren't in
the facts) and retried once. The overall sentiment is computed in code.
"""

import asyncio
import json
import logging
import re
import time
from collections import Counter
from collections.abc import AsyncIterator
from typing import Literal

from pydantic import BaseModel, Field

from services import llm
from services.facts import FactSheet
from services.impact import PersonalImpact
from services.personas import Persona
from services.pros_cons import NUMBER

log = logging.getLogger(__name__)

PARALLEL = 8
SUPPORT_AT = 0.2
"""Stances above this support, below minus this oppose, between are neutral."""

Theme = Literal[
    "housing", "affordability", "height_and_shadows", "green_space", "transit",
    "traffic_and_parking", "construction", "noise_and_crowds", "local_business", "jobs",
    "schools", "density", "walkability", "neighbourhood_character", "events_and_tourism",
]  # fmt: skip
SENTENCE_END = re.compile(r"[.!?]+(?=\s|$)")


class Reaction(BaseModel):
    stance: float = Field(ge=-1, le=1)
    reasons: list[str] = Field(min_length=2, max_length=2)
    quote: str = Field(min_length=10, max_length=400)
    themes: list[Theme] = Field(min_length=1, max_length=3)


class PersonaReaction(BaseModel):
    persona_id: str
    reaction: Reaction
    model: str
    latency_ms: int


def stance_label(stance: float) -> str:
    if stance > SUPPORT_AT:
        return "supports"
    if stance < -SUPPORT_AT:
        return "opposes"
    return "neutral"


def _profile(p: Persona) -> dict:
    return {
        "name": p.name,
        "age": p.age,
        "role": p.role,
        "occupation": p.occupation,
        "household": p.household,
        "tenure": p.tenure,
        "home": p.traits.get("housing"),
        "commute": p.commute_mode,
        "values": p.values,
        "quirks": p.traits.get("quirks", []),
        "openness_to_change": p.traits.get("openness"),
        "trust_in_government": p.traits.get("trust_in_government"),
        "backstory": p.backstory,
    }


def _problems(r: Reaction, allowed_text: str) -> list[str]:
    found = []
    sentences = len(SENTENCE_END.findall(r.quote.strip())) or 1
    if sentences > 3:
        found.append(f"the quote has {sentences} sentences; use 1 to 3")
    allowed = {float(n.replace(",", "")) for n in NUMBER.findall(allowed_text)}
    for field, value in (("quote", r.quote), *(("reason", x) for x in r.reasons)):
        stray = [n for n in NUMBER.findall(value) if float(n.replace(",", "")) not in allowed]
        if stray:
            found.append(
                f"the {field} uses numbers {stray} that are not in the facts, your impact or "
                "your profile; use only those numbers, or none"
            )
    return found


async def react(p: Persona, impact: PersonalImpact, sheet: FactSheet) -> PersonaReaction:
    payload = {
        "you": _profile(p),
        "proposal": {
            "type": sheet.type_label,
            "site": sheet.site_name,
            "parts_bottom_to_top": [p.model_dump() for p in sheet.parts] or sheet.params,
            "impact_radius_m": sheet.impact_radius_m,
        },
        "how_it_affects_you": impact.bullets,
        "facts": [f"{f.label}: {f.display}" for f in sheet.facts],
    }
    user = json.dumps(payload, ensure_ascii=False, indent=1)
    started = time.monotonic()
    reaction, model = await llm.complete_json(
        system=llm.prompt("persona_react"),
        user=user,
        schema=Reaction,
        check=lambda r: _problems(r, user),
        model=p.model,
        max_tokens=1000,
    )
    return PersonaReaction(
        persona_id=str(p.id),
        reaction=reaction,
        model=model,
        latency_ms=round((time.monotonic() - started) * 1000),
    )


async def react_all(
    personas: list[Persona], impacts: dict, sheet: FactSheet
) -> AsyncIterator[tuple[Persona, PersonaReaction | None]]:
    """Reactions in the order they finish; None for a persona whose replies failed twice."""
    gate = asyncio.Semaphore(PARALLEL)

    async def one(p: Persona) -> tuple[Persona, PersonaReaction | None]:
        async with gate:
            try:
                return p, await react(p, impacts[p.id], sheet)
            except llm.LLMError:
                log.warning("persona %s (%s) gave no valid reaction", p.name, p.id)
                return p, None

    for next_done in asyncio.as_completed([one(p) for p in personas]):
        yield await next_done


class ThemeCount(BaseModel):
    theme: str
    count: int
    support: int
    oppose: int


class Sentiment(BaseModel):
    count: int
    mean: float
    support: float
    neutral: float
    oppose: float
    """Shares of personas, 0..1."""
    label: str
    themes: list[ThemeCount]


def sentiment(reactions: list[Reaction]) -> Sentiment:
    n = len(reactions)
    if n == 0:
        return Sentiment(count=0, mean=0, support=0, neutral=0, oppose=0, label="No reactions",
                         themes=[])  # fmt: skip
    labels = Counter(stance_label(r.stance) for r in reactions)
    mean = sum(r.stance for r in reactions) / n
    support, oppose = labels["supports"] / n, labels["opposes"] / n
    if support >= 0.6:
        label = "Strong support"
    elif oppose >= 0.6:
        label = "Strong opposition"
    elif support - oppose >= 0.15:
        label = "Leaning support"
    elif oppose - support >= 0.15:
        label = "Leaning oppose"
    else:
        label = "Divided"
    themes: dict[str, Counter] = {}
    for r in reactions:
        for t in set(r.themes):
            themes.setdefault(t, Counter())[stance_label(r.stance)] += 1
    top = sorted(themes.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))[:5]
    return Sentiment(
        count=n,
        mean=round(mean, 2),
        support=round(support, 3),
        neutral=round(labels["neutral"] / n, 3),
        oppose=round(oppose, 3),
        label=label,
        themes=[
            ThemeCount(theme=t, count=sum(c.values()), support=c["supports"], oppose=c["opposes"])
            for t, c in top
        ],
    )


def card(p: Persona, impact: PersonalImpact, r: PersonaReaction) -> dict:
    """Everything the results panel shows for one persona."""
    return {
        "persona": {
            "id": str(p.id),
            "name": p.name,
            "age": p.age,
            "role": p.role,
            "occupation": p.occupation,
            "tagline": p.traits.get("tagline", p.occupation),
            "based_on": p.traits.get("based_on"),
        },
        "pin": list(impact.pin),
        "distance_m": impact.pin_distance_m,
        "bullets": impact.bullets,
        "stance": r.reaction.stance,
        "stance_label": stance_label(r.reaction.stance),
        "reasons": r.reaction.reasons,
        "quote": r.reaction.quote,
        "themes": r.reaction.themes,
        "model": r.model,
    }
