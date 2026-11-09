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
