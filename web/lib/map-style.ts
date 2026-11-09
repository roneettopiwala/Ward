import bbox from "@turf/bbox";
import buffer from "@turf/buffer";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import type { FilterSpecification, StyleSpecification } from "maplibre-gl";

import {
  BASEMAP_SOURCE,
  basemapGlyphs,
  basemapLayers,
  basemapSource,
  buildingsLayer,
  labelLayers,
} from "./basemap";
import type { MapTokens } from "./tokens";
import type { BaseFeature, CatalogType, Proposal } from "./types";

export const SELECTION_SOURCE = "selection";
export const SELECTION_CORNERS_SOURCE = "selection-corners";
export const SELECTION_HIGHLIGHT_SOURCE = "selection-highlight";
export const REMOVED_SOURCE = "removed";
export const PROPOSALS_SOURCE = "proposals";
export const IMPACT_SOURCE = "impact";
export const CORNER_IMAGE = "corner-handle";

/** Height for a proposal whose type has no height (or isn't in the catalog). */
export const PLACEHOLDER_HEIGHT_M = 40;
/** Flat proposals (parks) sit just above the ground so buildings still occlude them. */
const FLAT_HEIGHT_M = 0.6;

const empty: FeatureCollection = { type: "FeatureCollection", features: [] };

const isArea: FilterSpecification = [
  "in",
  ["geometry-type"],
  ["literal", ["Polygon", "MultiPolygon"]],
];

export function buildStyle(t: MapTokens): StyleSpecification {
  return {
    version: 8,
    glyphs: basemapGlyphs,
    light: { anchor: "viewport", color: "#ffffff", intensity: 0.4, position: [1.15, 210, 30] },
    sources: {
      [BASEMAP_SOURCE]: basemapSource,
      [REMOVED_SOURCE]: { type: "geojson", data: empty },
      [SELECTION_SOURCE]: { type: "geojson", data: empty },
      [SELECTION_CORNERS_SOURCE]: { type: "geojson", data: empty },
      [SELECTION_HIGHLIGHT_SOURCE]: { type: "geojson", data: empty },
      [PROPOSALS_SOURCE]: { type: "geojson", data: empty },
      [IMPACT_SOURCE]: { type: "geojson", data: empty },
    },
    layers: [
      ...basemapLayers(t),
      {
        id: "selection-fill",
        type: "fill",
        source: SELECTION_SOURCE,
        paint: { "fill-color": t.accent, "fill-opacity": 0.08 },
      },
      {
        id: "impact-fill",
        type: "fill",
        source: IMPACT_SOURCE,
        paint: { "fill-color": t.accent, "fill-opacity": 0.04 },
      },
      {
        id: "impact-outline",
        type: "line",
        source: IMPACT_SOURCE,
        paint: { "line-color": t.accent, "line-width": 1.5, "line-dasharray": [2, 2], "line-opacity": 0.7 },
      },
      buildingsLayer(t, []),
      {
        // Drawn over the selected building when the basemap can't highlight it alone.
        id: "selection-highlight",
        type: "fill-extrusion",
        source: SELECTION_HIGHLIGHT_SOURCE,
        paint: {
          "fill-extrusion-color": t.buildingSelected,
          "fill-extrusion-height": ["+", ["get", "height"], 0.3],
        },
      },
      {
        id: "proposals-area",
        type: "fill-extrusion",
        source: PROPOSALS_SOURCE,
        filter: isArea,
        paint: {
          "fill-extrusion-color": ["get", "color"],
          "fill-extrusion-height": ["get", "height"],
          "fill-extrusion-opacity": 0.9,
        },
      },
      {
        id: "proposals-line",
        type: "line",
        source: PROPOSALS_SOURCE,
        filter: ["==", ["geometry-type"], "LineString"],
        paint: { "line-color": t.accent, "line-width": 4 },
      },
      {
        id: "proposals-point",
        type: "circle",
        source: PROPOSALS_SOURCE,
        filter: ["==", ["geometry-type"], "Point"],
        paint: { "circle-color": t.accent, "circle-radius": 6 },
      },
      {
        id: "removed-outline",
        type: "line",
        source: REMOVED_SOURCE,
        paint: { "line-color": t.removed, "line-width": 1.5, "line-dasharray": [3, 2] },
      },
      {
        id: "selection-outline",
        type: "line",
        source: SELECTION_SOURCE,
        paint: { "line-color": t.accent, "line-width": 1.5, "line-dasharray": [3, 2] },
      },
      {
        id: "selection-corners",
        type: "symbol",
        source: SELECTION_CORNERS_SOURCE,
        layout: { "icon-image": CORNER_IMAGE, "icon-allow-overlap": true },
      },
      ...labelLayers(t),
    ],
  };
}

export function toCollection(geometries: Geometry[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: geometries.map((geometry): Feature => ({ type: "Feature", properties: {}, geometry })),
  };
}

/** Proposals styled by their catalog type: extruded by height, or flat (parks). */
export function proposalsCollection(
  proposals: Proposal[],
  catalog: CatalogType[],
  t: MapTokens,
): FeatureCollection {
  const types = new Map(catalog.map((c) => [c.type, c]));
  return {
    type: "FeatureCollection",
    features: proposals.map((p): Feature => {
      const render = types.get(p.type)?.render;
      const flat = render?.kind === "flat";
      const height = render?.heightParam ? p.params[render.heightParam] : undefined;
      const color = render ? t[render.color as keyof MapTokens] : undefined;
      return {
        type: "Feature",
        id: p.id,
        properties: {
          type: p.type,
          height: flat ? FLAT_HEIGHT_M : (height ?? PLACEHOLDER_HEIGHT_M),
          color: color ?? t.accent,
        },
        geometry: p.geometry,
      };
    }),
  };
}

/** The area a proposal's metrics cover: its footprint grown by the impact radius. */
export function impactArea(geometry: Geometry, radiusM: number): FeatureCollection {
  const area = buffer(geometry, radiusM, { units: "meters" });
  if (!area) return empty;
  return area.type === "FeatureCollection" ? area : { type: "FeatureCollection", features: [area] };
}

/**
 * Corners of the footprint's bounding box, aligned to the map's rotation so
 * the selection handles sit square on screen. Uses a local flat projection,
 * which is plenty accurate at building scale.
 */
export function cornerPoints(feature: BaseFeature, bearingDeg: number): FeatureCollection {
  const [w, s, e, n] = bbox(feature.footprint);
  const [cx, cy] = [(w + e) / 2, (s + n) / 2];
  const kx = Math.cos((cy * Math.PI) / 180);
  const a = (bearingDeg * Math.PI) / 180;
  const [cos, sin] = [Math.cos(a), Math.sin(a)];
  // Into screen-aligned axes (u right, v up), and back.
  const toUV = ([x, y]: number[]) => {
    const [dx, dy] = [(x - cx) * kx, y - cy];
    return [dx * cos - dy * sin, dx * sin + dy * cos];
  };
  const fromUV = ([u, v]: number[]) => [cx + (u * cos + v * sin) / kx, cy - u * sin + v * cos];

  const uv = coordsOf(feature.footprint).map(toUV);
  const us = uv.map(([u]) => u);
  const vs = uv.map(([, v]) => v);
  const [u0, u1, v0, v1] = [Math.min(...us), Math.max(...us), Math.min(...vs), Math.max(...vs)];
  return toCollection(
    [
      [u0, v0],
      [u0, v1],
      [u1, v0],
      [u1, v1],
    ].map((corner) => ({ type: "Point", coordinates: fromUV(corner) })),
  );
}

function coordsOf(footprint: BaseFeature["footprint"]): number[][] {
  return footprint.type === "Polygon" ? footprint.coordinates.flat() : footprint.coordinates.flat(2);
}

/** A small square handle, drawn once so no sprite sheet is needed. */
export function cornerImage(t: MapTokens): { width: number; height: number; data: Uint8Array } {
  const size = 10;
  const hex = (c: string) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
  const [fill, edge] = [hex(t.bg), hex(t.accent)];
  const data = new Uint8Array(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const border = x < 2 || y < 2 || x >= size - 2 || y >= size - 2;
      data.set([...(border ? edge : fill), 255], (y * size + x) * 4);
    }
  }
  return { width: size, height: size, data };
}
