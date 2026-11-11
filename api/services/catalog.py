"""The type catalog: every buildable type, loaded from api/catalog/*.yaml."""

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


class TypeDef(BaseModel):
    type: str
    label: str
    description: str = ""
    """What the type covers; the prompt parser maps requests with it."""
    geometry: GeometryKind
    params: dict[str, Param]
    render: Render
    impact_radius_m: float
    storey_m: float | None = None
    impact_metrics: list[str]
    relevant_to: list[str]

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
    """One part of a proposal: a catalog type with its params, e.g. a retail podium."""

    type: str
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
        return cls(parts=[(p, types[p.type]) for p in parts])

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
        """A park covering the whole site at ground level."""
        return not self.mixed and self.parts[0][1].type == "park"

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
