"""The catalog: every buildable class of thing, loaded from api/catalog/*.yaml.

Each file is a use class (residential, retail and food, open space...) with the
params, draw rules, render style, metrics and persona relevance its buildings
share. Specific buildings are subtypes of a class (a condo tower, townhouses,
a community garden); a subtype can set its own defaults and override any class
field. A part names its class (`type`) and subtype; `resolve` gives the
effective definition everything else works from. A subtype the catalog doesn't
know ("cat café") behaves like the class's default subtype under its own name.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

CATALOG_DIR = Path(__file__).resolve().parent.parent / "catalog"

GeometryKind = Literal["polygon", "line", "point"]
# GeoJSON geometry types each catalog geometry kind accepts.
GEOMETRY_TYPES: dict[GeometryKind, set[str]] = {
    "polygon": {"Polygon", "MultiPolygon"},
    "line": {"LineString", "MultiLineString"},
    "point": {"Point", "MultiPoint"},
}


class Param(BaseModel):
    label: str
    unit: str | None = None
    default: float
    min: float
    max: float
    step: float = 1
    main: bool = False
    """Shown in the type picker."""


class Render(BaseModel):
    kind: Literal["extrusion", "flat", "line", "point"]
    color: str
    """A map token name, e.g. accent or park."""
    height_param: str | None = None


DrawTool = Literal["lot", "rectangle", "polygon", "freehand", "route", "point"]


class Draw(BaseModel):
    """How a type is drawn on the map, and what counts as a valid shape for it."""

    tools: list[DrawTool]
    min_area_m2: float | None = None
    max_area_m2: float | None = None
    min_length_m: float | None = None
    max_length_m: float | None = None
    snap: Literal["vertices", "street", "none"] = "vertices"
    """Areas snap to building and lot corners; points can snap to the nearest street."""


class Subtype(BaseModel):
    """A specific kind of building within a class. Unset fields come from the class."""

    label: str
    description: str = ""
    params: dict[str, Param] = {}
    """Added to the class's params, or replacing one with the same name."""
    defaults: dict[str, float] = {}
    """New defaults for class params, e.g. a lower height for townhouses."""
    render: Render | None = None
    draw: Draw | None = None
    impact_metrics: list[str] | None = None
    relevant_to: list[str] | None = None
    green_space: bool | None = None
    impact_radius_m: float | None = None


FREE_SUBTYPE_CHARS = 40
"""Longest name for a subtype the catalog doesn't list, e.g. "cat café"."""


class TypeDef(BaseModel):
    type: str
    """The class id, e.g. residential."""
    label: str
    """The class label, or the subtype's once resolved."""
    description: str = ""
    """What the class covers; the prompt parser maps requests with it."""
    geometry: GeometryKind
    params: dict[str, Param]
    render: Render
    impact_radius_m: float
    storey_m: float | None = None
    impact_metrics: list[str]
    relevant_to: list[str]
    draw: Draw
    green_space: bool = False
    """Counts as public green space (parks, community gardens) when it covers a site."""
    zone_classes: list[str] = []
    """Zone classes (By-law 569-2013) whose permitted uses broadly include this class."""
    subtypes: dict[str, Subtype] = {}
    default_subtype: str = ""
    subtype: str | None = None
    """Set once resolved: the subtype id, or a free-text name the catalog doesn't list."""
    class_label: str = ""
    """Set once resolved: the class's own label."""

    def resolve(self, subtype: str | None) -> "TypeDef":
        """The effective definition for a subtype (the default one when None)."""
        known = subtype if subtype in self.subtypes else self.default_subtype
        sub = self.subtypes.get(known)
        out = self.model_copy(deep=True)
        out.subtypes = {}
        out.class_label = self.label
        out.subtype = subtype if subtype and subtype not in self.subtypes else known or None
        if sub is None:
            return out
        out.label = sub.label
        out.description = sub.description or self.description
        out.params = {**self.params, **sub.params}
        for name, value in sub.defaults.items():
            if name in out.params:
                out.params[name] = out.params[name].model_copy(update={"default": value})
        for field in ("render", "draw", "impact_metrics", "relevant_to", "green_space",
                      "impact_radius_m"):  # fmt: skip
            if (value := getattr(sub, field)) is not None:
                setattr(out, field, value)
        if subtype and subtype not in self.subtypes:
            out.label = subtype[:1].upper() + subtype[1:]
        return out

    def normalise_subtype(self, name: str | None) -> str | None:
        """A known subtype id (also from its label), tidied free text, or the default."""
        if not name or not name.strip():
            return self.default_subtype or None
        name = " ".join(name.split())
        if name in self.subtypes:
            return name
        for key, sub in self.subtypes.items():
            if name.lower() in (sub.label.lower(), key.replace("_", " ")):
                return key
        return name.lower()[:FREE_SUBTYPE_CHARS]

    def expanded(self) -> list["TypeDef"]:
        """Every listed subtype as an effective definition (what the web app picks from)."""
        return [self.resolve(key) for key in self.subtypes] or [self.resolve(None)]

    def resolve_params(self, given: dict[str, Any]) -> dict[str, float]:
        """Defaults filled in; raises ValueError on unknown or out-of-range values."""
        unknown = set(given) - set(self.params)
        if unknown:
            raise ValueError(f"unknown params for {self.type}: {sorted(unknown)}")
        out: dict[str, float] = {}
        for name, p in self.params.items():
            value = given.get(name, p.default)
            if not isinstance(value, int | float) or isinstance(value, bool):
                raise ValueError(f"{name} must be a number")
            if not p.min <= value <= p.max:
                raise ValueError(f"{name} must be between {p.min:g} and {p.max:g}")
            out[name] = float(value)
        return out


@lru_cache
def catalog() -> dict[str, TypeDef]:
    paths = CATALOG_DIR.glob("*.yaml")
    types = [TypeDef.model_validate(yaml.safe_load(p.read_text())) for p in paths]
    return {t.type: t for t in sorted(types, key=lambda t: t.label)}


class Part(BaseModel):
    """One part of a proposal: a class and subtype with params, e.g. a retail podium."""

    type: str
    """The class id."""
    subtype: str | None = None
    """A subtype id, a short free-text name, or None for the class's default."""
    params: dict[str, float] = {}
    tags: list[str] = []
    """What it is beyond its catalog type, e.g. ["food hall"]."""


class Stack(BaseModel):
    """A proposal's parts with their catalog types, bottom to top.

    Extruded parts stack on each other; a flat part (a park) covers the site
    when it's alone and sits on the roof otherwise.
    """

    parts: list[tuple[Part, TypeDef]]

    @classmethod
    def of(cls, parts: list[Part]) -> "Stack":
        types = catalog()
        return cls(parts=[(p, types[p.type].resolve(p.subtype)) for p in parts])

    @property
    def mixed(self) -> bool:
        return len(self.parts) > 1

    @property
    def main(self) -> tuple[Part, TypeDef]:
        """The tallest extruded part (what the building mostly is), else the first."""
        built = [(p, t) for p, t in self.parts if t.render.kind == "extrusion"]
        return max(built, key=lambda pt: self.part_height(*pt)) if built else self.parts[0]

    @staticmethod
    def part_height(part: Part, typedef: TypeDef) -> float:
        param = typedef.render.height_param
        return part.params.get(param, 0.0) if param else 0.0

    @property
    def height_m(self) -> float | None:
        heights = [self.part_height(p, t) for p, t in self.parts if t.render.height_param]
        return sum(heights) if heights else None

    @property
    def storeys(self) -> int | None:
        counts = [
            max(1, round(self.part_height(p, t) / t.storey_m))
            for p, t in self.parts
            if t.render.height_param and t.storey_m
        ]
        return sum(counts) if counts else None

    @property
    def units(self) -> float | None:
        units = [p.params["units"] for p, _ in self.parts if "units" in p.params]
        return sum(units) if units else None

    @property
    def site_park(self) -> bool:
        """Green space (a park or garden) covering the whole site at ground level."""
        return not self.mixed and self.parts[0][1].green_space

    @property
    def roof_parks(self) -> list[Part]:
        return [p for p, t in self.parts if self.mixed and t.render.kind == "flat"]

    def part_label(self, part: Part, typedef: TypeDef) -> str:
        label = typedef.label
        if self.mixed and typedef.render.kind == "flat":
            label = f"Rooftop {label.lower()}"
        return f"{label} ({', '.join(part.tags)})" if part.tags else label

    @property
    def label(self) -> str:
        """E.g. "Mall (food hall) + Rooftop park"."""
        return " + ".join(self.part_label(p, t) for p, t in self.parts)

    @property
    def impact_radius_m(self) -> float:
        return max(t.impact_radius_m for _, t in self.parts)

    @property
    def impact_metrics(self) -> list[str]:
        return list(dict.fromkeys(m for _, t in self.parts for m in t.impact_metrics))

    @property
    def relevant_to(self) -> list[str]:
        return list(dict.fromkeys(g for _, t in self.parts for g in t.relevant_to))
