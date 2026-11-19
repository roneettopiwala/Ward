/**
 * Helpers for a proposal's parts, bottom to top. Mirrors api/services/catalog.py
 * (Stack): extruded parts stack, and a flat part (a park) covers the site when
 * alone and sits on the roof otherwise.
 */
import type { CatalogType, Geometry, Part } from "./types";

/** Keyed "class/subtype", plus "class" for the class's default subtype. */
export type Catalog = Map<string, CatalogType>;

export function catalogMap(catalog: CatalogType[]): Catalog {
  const map: Catalog = new Map();
  for (const t of catalog) {
    map.set(`${t.type}/${t.subtype}`, t);
    if (t.subtype === t.defaultSubtype) map.set(t.type, t);
  }
  return map;
}

/** A part's effective type; a subtype the catalog doesn't list behaves like the default. */
export function typeOf(part: Pick<Part, "type" | "subtype">, catalog: Catalog): CatalogType | undefined {
  return catalog.get(`${part.type}/${part.subtype}`) ?? catalog.get(part.type);
}

/** A part's name: its subtype's label, or a free-text subtype as written. */
function nameOf(part: Part, catalog: Catalog): string {
  if (part.subtype && !catalog.has(`${part.type}/${part.subtype}`)) {
    return part.subtype.charAt(0).toUpperCase() + part.subtype.slice(1);
  }
  return typeOf(part, catalog)?.label ?? part.type;
}

export function defaultParams(t: CatalogType): Record<string, number> {
  return Object.fromEntries(Object.entries(t.params).map(([name, p]) => [name, p.default]));
}

export function partHeight(part: Part, t: CatalogType | undefined): number {
  const param = t?.render.heightParam;
  return param ? (part.params[param] ?? t.params[param]?.default ?? 0) : 0;
}

export function storeysOf(heightM: number, t: CatalogType | undefined): number | null {
  return t?.storeyM ? Math.max(1, Math.round(heightM / t.storeyM)) : null;
}

export function isRoof(parts: Part[], index: number, catalog: Catalog): boolean {
  return parts.length > 1 && typeOf(parts[index], catalog)?.render.kind === "flat";
}

export function partLabel(parts: Part[], index: number, catalog: Catalog): string {
  const part = parts[index];
  const base = nameOf(part, catalog);
  return isRoof(parts, index, catalog) ? `Rooftop ${base.toLowerCase()}` : base;
}

/** "Mall + Rooftop park", or "Mixed-use" past two parts. */
export function stackLabel(parts: Part[], catalog: Catalog): string {
  if (parts.length > 2) return "Mixed-use";
  return parts.map((_, i) => partLabel(parts, i, catalog)).join(" + ");
}

/** Total height and storeys of the built parts. */
export function stackHeight(parts: Part[], catalog: Catalog): { heightM: number; storeys: number } {
  let heightM = 0;
  let storeys = 0;
  for (const part of parts) {
    const t = typeOf(part, catalog);
    const h = partHeight(part, t);
    heightM += h;
    if (h) storeys += storeysOf(h, t) ?? 0;
  }
  return { heightM, storeys };
}

export function homesOf(parts: Part[]): number | null {
  const units = parts.map((p) => p.params.units).filter((u): u is number => u !== undefined);
  return units.length ? units.reduce((a, b) => a + b, 0) : null;
}

/** Where a new part of this type goes: flat parts on the roof, buildings under the roof. */
export function insertPart(parts: Part[], part: Part, catalog: Catalog): Part[] {
  const isFlat = (p: Part) => typeOf(p, catalog)?.render.kind === "flat";
  // One roof: a new flat part replaces any existing one.
  if (isFlat(part)) return [...parts.filter((p) => !isFlat(p)), part];
  const flatAt = parts.findIndex(isFlat);
  if (flatAt === -1) return [...parts, part];
  return [...parts.slice(0, flatAt), part, ...parts.slice(flatAt)];
}

export function largestRadius(parts: Part[], catalog: Catalog): number | null {
  const radii = parts.map((p) => typeOf(p, catalog)?.impactRadiusM ?? 0);
  return radii.length ? Math.max(...radii) : null;
}

const count = new Intl.NumberFormat("en-CA", { maximumFractionDigits: 0 });

/** "8 storeys · 400 homes" for a subtitle. */
export function stackSummary(parts: Part[], catalog: Catalog): string {
  const { heightM, storeys } = stackHeight(parts, catalog);
  const homes = homesOf(parts);
  return [
    storeys ? `${storeys} storey${storeys === 1 ? "" : "s"}` : heightM ? `${count.format(heightM)} m` : null,
    homes ? `${count.format(homes)} homes` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** Catalog types that can go on a site of this shape (area, line or point). */
export function typesFor(catalog: CatalogType[], geometry: Geometry): CatalogType[] {
  const shape =
    geometry.type === "LineString" || geometry.type === "MultiLineString"
      ? "line"
      : geometry.type === "Point" || geometry.type === "MultiPoint"
        ? "point"
        : "polygon";
  return catalog.filter((t) => t.geometry === shape);
}
