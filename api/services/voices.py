"""Persona voices: how each persona talks, fixed for life.

One model writes every reaction, so without help fifteen people come out
sounding like the same careful essay. A voice is a handful of choices about
*how* someone argues (length, directness, the kind of reasoning they reach
for, how much feeling shows, how they open), drawn in code from a seed so
it never changes between proposals.

Voices are mostly random, lightly nudged by a persona's situation (a parent
of young kids leans short, a long-time retiree leans on stories). They never
follow from ethnicity, language, income or neighbourhood, and never mean an
accent, dialect or slang: quotes stay in plain English.
"""

import random
from dataclasses import dataclass
from typing import Any

# Each dimension: option -> (base weight, what the reaction prompt is told).
LENGTH = {
    "short": (0.35, "Say it in one short sentence, under 25 words. Pick your one main point."),
    "medium": (0.40, "Say it in one or two sentences, under 50 words."),
    "full": (0.25, "Take two or three sentences."),
}
DIRECTNESS = {
    "blunt": (0.30, "Be blunt and plain-spoken; no softening."),
    "measured": (0.45, "Be measured: say what you think, calmly."),
    "hedging": (0.25, "Hedge a little; you see some of the other side."),
}
REASONING = {
    "story": (0.25, "Make your point through something from your own life."),
    "practical": (0.35, "Make your point through practical, everyday details."),
    "costs": (0.20, "Make your point through money, time or other costs."),
    "question": (0.20, "Make your point partly as a pointed question."),
}
EXPRESSIVENESS = {
    "reserved": (0.30, "Keep your feelings understated."),
    "plain": (0.45, "Let your feelings show only as much as they are."),
    "animated": (0.25, "Let your feelings show clearly, whichever way you lean."),
}
OPENING = {
    "view": (0.45, "Start with your view."),
    "impact": (0.35, "Start with how it affects you."),
    "context": (0.20, "Start with a bit of context about yourself or the place."),
}
DIMENSIONS = {
    "length": LENGTH,
    "directness": DIRECTNESS,
    "reasoning": REASONING,
    "expressiveness": EXPRESSIVENESS,
    "opening": OPENING,
}
MAX_SENTENCES = {"short": 1, "medium": 2, "full": 3}
MAX_WORDS = {"short": 30, "medium": 60, "full": 90}
"""A little above what the prompt asks, so only clear overruns are retried."""
NUDGE = 1.6
"""How much a situation multiplies an option's weight: a lean, not a rule."""


@dataclass
class Situation:
    """The parts of a persona that may nudge their voice. Nothing about identity."""

    seed: str
    age: int
    role: str
    occupation_group: str | None
    has_children: bool
    stubbornness: float
    openness: float
    tags: list[str]


def _nudges(s: Situation) -> dict[str, dict[str, float]]:
    n: dict[str, dict[str, float]] = {d: {} for d in DIMENSIONS}

    def lean(dim: str, option: str) -> None:
        n[dim][option] = n[dim].get(option, 1.0) * NUDGE

    if s.has_children:
        lean("length", "short")
        lean("opening", "impact")
    if s.role == "worker":
        lean("length", "short")
        lean("reasoning", "practical")
    if s.occupation_group == "retired" or s.age >= 65:
        lean("length", "full")
        lean("reasoning", "story")
    if s.occupation_group in ("business_finance_admin", "management") or "local_business" in s.tags:
        lean("reasoning", "costs")
    if s.stubbornness >= 0.7:
        lean("directness", "blunt")
    if s.openness >= 0.7:
        lean("directness", "hedging")
    return n


def assign(s: Situation) -> dict[str, str]:
    """A voice for this persona. The same situation always gets the same voice."""
    rng = random.Random(f"voice:{s.seed}")
    nudges = _nudges(s)
    voice = {}
    for dim, options in DIMENSIONS.items():
        names = list(options)
        weights = [options[o][0] * nudges[dim].get(o, 1.0) for o in names]
        voice[dim] = rng.choices(names, weights=weights)[0]
    return voice


def situation(
    seed: str, age: int, role: str, stubbornness: float, traits: dict[str, Any]
) -> Situation:
    return Situation(
        seed=seed,
        age=age,
        role=role,
        occupation_group=traits.get("occupation_group"),
        has_children=bool(traits.get("has_children")),
        stubbornness=stubbornness,
        openness=float(traits.get("openness") or 0.5),
        tags=list(traits.get("tags", [])),
    )


def describe(voice: dict[str, str]) -> list[str]:
    """The voice as instructions for the reaction prompt."""
    return [DIMENSIONS[d][voice[d]][1] for d in DIMENSIONS if voice.get(d) in DIMENSIONS[d]]


def max_sentences(voice: dict[str, str] | None) -> int:
    return MAX_SENTENCES.get((voice or {}).get("length", "full"), 3)


def max_words(voice: dict[str, str] | None) -> int:
    return MAX_WORDS.get((voice or {}).get("length", "full"), 90)
