/**
 * Ward's own map layers, served as PMTiles (built by `python -m ward_pipeline.tiles`).
 *
 * Every feature carries its Ward fid, promoted to the feature id, so selection
 * highlights and hidden (replaced) features work directly by fid.
 */
import type {
  ExpressionSpecification,
  LayerSpecification,
  Map as MapLibreMap,
  MapGeoJSONFeature,
  PointLike,
  SourceSpecification,
} from "maplibre-gl";

import type { MapTokens } from "./tokens";
import type { BaseFeature, FeatureKind, Fid } from "./types";

/** Tile layers (one PMTiles file each) and the feature kind each holds. */
const TILESETS = {
  buildings: "building",
  parcels: "parcel",
  parks: "park",
  streets: "street",
  cycling: "cycling",
  transit: "transit",
} as const satisfies Record<string, FeatureKind>;
type Tileset = keyof typeof TILESETS;

const KIND_TILESET = Object.fromEntries(
  Object.entries(TILESETS).map(([tileset, kind]) => [kind, tileset]),
) as Record<FeatureKind, Tileset>;

const sourceId = (tileset: Tileset) => `city-${tileset}`;

export const BUILDINGS_LAYER = "city-buildings-3d";
const PARCELS_HIT_LAYER = "city-parcels-hit";
const PARKS_LAYER = "city-parks";
const STREETS_LAYER = "city-streets";
const CYCLING_LAYER = "city-cycling";
const TRANSIT_LAYER = "city-transit";

/**
 * Click priority, highest first: buildings, points, lines, parks, parcels.
 * Points and lines are thin, so they are hit within a few pixels of the click.
 */
const HIT_ORDER = [
  BUILDINGS_LAYER,
  TRANSIT_LAYER,
  CYCLING_LAYER,
  STREETS_LAYER,
  PARKS_LAYER,
  PARCELS_HIT_LAYER,
];
const NEAR_PX = 6;
const NEAR_LAYERS = new Set([TRANSIT_LAYER, CYCLING_LAYER, STREETS_LAYER]);
export const HIT_LAYERS = HIT_ORDER;

/** Below this many metres of building height in the data, draw a low block. */
const DEFAULT_HEIGHT_M = 6;

export function citySources(origin: string): Record<string, SourceSpecification> {
  return Object.fromEntries(
    (Object.keys(TILESETS) as Tileset[]).map((tileset) => [
      sourceId(tileset),
      {
        type: "vector",
        url: `pmtiles://${origin}/tiles/${tileset}.pmtiles`,
        promoteId: "fid",
        attribution: "© City of Toronto",
      } satisfies SourceSpecification,
    ]),
  );
}

const isSelected: ExpressionSpecification = ["boolean", ["feature-state", "selected"], false];

/** Ground-level layers: parks, parcels and streets, drawn under the buildings. */
export function groundLayers(t: MapTokens, hidden: Fid[]): LayerSpecification[] {
  return [
    {
      id: PARKS_LAYER,
      type: "fill",
      source: sourceId("parks"),
      "source-layer": "parks",
      filter: notHidden(hidden),
      paint: { "fill-color": t.park },
    },
    {
      // Invisible: lets a click find the lot under it.
      id: PARCELS_HIT_LAYER,
      type: "fill",
      source: sourceId("parcels"),
      "source-layer": "parcels",
      filter: notHidden(hidden),
      paint: { "fill-opacity": 0 },
    },
    {
      id: "city-parcels-line",
      type: "line",
      source: sourceId("parcels"),
      "source-layer": "parcels",
      minzoom: 16,
      filter: notHidden(hidden),
      paint: { "line-color": t.label, "line-opacity": 0.18, "line-width": 0.5 },
    },
    {
      id: STREETS_LAYER,
      type: "line",
      source: sourceId("streets"),
      "source-layer": "streets",
      filter: ["!", ["in", ["get", "road_class"], ["literal", ["trail", "walkway"]]]],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": t.road,
        "line-width": [
          "interpolate",
          ["exponential", 1.6],
          ["zoom"],
          12,
          ["match", ["get", "road_class"], ["expressway", "major_arterial"], 2, 0.6],
          16,
          ["match", ["get", "road_class"], ["expressway", "major_arterial"], 16, "laneway", 3, 9],
          19,
          ["match", ["get", "road_class"], ["expressway", "major_arterial"], 60, "laneway", 12, 36],
        ],
      },
    },
    {
      id: CYCLING_LAYER,
      type: "line",
      source: sourceId("cycling"),
      "source-layer": "cycling",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": t.cycling,
        "line-opacity": ["match", ["get", "facility_type"], "shared", 0.45, 0.85],
        "line-width": ["interpolate", ["linear"], ["zoom"], 11, 1, 16, 2.5],
        "line-dasharray": [
          "match",
          ["get", "facility_type"],
          "shared",
          ["literal", [2, 2]],
          ["literal", [1, 0]],
        ],
      },
    },
  ];
}

/** 3D buildings, minus hidden (removed or replaced) ones. */
export function buildingsLayer(t: MapTokens, hidden: Fid[]): LayerSpecification {
  return {
    id: BUILDINGS_LAYER,
    type: "fill-extrusion",
    source: sourceId("buildings"),
    "source-layer": "buildings",
    filter: notHidden(hidden),
    paint: {
      "fill-extrusion-color": ["case", isSelected, t.buildingSelected, t.building],
      "fill-extrusion-height": ["coalesce", ["get", "height"], DEFAULT_HEIGHT_M],
      "fill-extrusion-opacity": 1,
    },
  };
}

/** Transit stops, above the buildings so they stay clickable. */
export function transitLayer(t: MapTokens): LayerSpecification {
  return {
    id: TRANSIT_LAYER,
    type: "circle",
    source: sourceId("transit"),
    "source-layer": "transit",
    minzoom: 14,
    paint: {
      "circle-color": t.transit,
      "circle-radius": [
        "case",
        isSelected,
        6,
        ["match", ["get", "mode"], ["subway", "lrt"], 4.5, 3],
      ],
      "circle-stroke-color": ["case", isSelected, t.accent, t.bg],
      "circle-stroke-width": ["case", isSelected, 2, 1],
      "circle-pitch-alignment": "map",
    },
  };
}

/** The layers whose filters hide replaced or removed features. */
export const HIDEABLE_LAYERS = [
  BUILDINGS_LAYER,
  PARKS_LAYER,
  PARCELS_HIT_LAYER,
  "city-parcels-line",
];

export function notHidden(hidden: Fid[]): ExpressionSpecification {
  return ["!", ["in", ["get", "fid"], ["literal", hidden]]];
}

export function kindOf(fid: Fid): FeatureKind | null {
  const prefix = fid.split(":", 1)[0];
  return prefix in KIND_TILESET ? (prefix as FeatureKind) : null;
}

/** Highlight (or clear) a feature in its tile layer. */
export function setSelectedState(map: MapLibreMap, fid: Fid, selected: boolean): void {
  const kind = kindOf(fid);
  if (!kind) return;
  const tileset = KIND_TILESET[kind];
  map.setFeatureState({ source: sourceId(tileset), sourceLayer: tileset, id: fid }, { selected });
}

/**
 * Every feature under a click, best first: one per fid, in click priority.
 * Geometry comes from the tile (clipped at tile edges); the API has the full shape.
 */
export function featuresAt(map: MapLibreMap, point: { x: number; y: number }): BaseFeature[] {
  const near: [PointLike, PointLike] = [
    [point.x - NEAR_PX, point.y - NEAR_PX],
    [point.x + NEAR_PX, point.y + NEAR_PX],
  ];
  const seen = new Set<Fid>();
  const out: BaseFeature[] = [];
  for (const layer of HIT_ORDER) {
    if (!map.getLayer(layer)) continue;
    const hits = map.queryRenderedFeatures(NEAR_LAYERS.has(layer) ? near : [point.x, point.y], {
      layers: [layer],
    });
    for (const hit of hits) {
      const feature = toBaseFeature(hit);
      if (feature && !seen.has(feature.fid)) {
        seen.add(feature.fid);
        out.push(feature);
        break; // the top feature of each layer is enough
      }
    }
  }
  return out;
}

function toBaseFeature(hit: MapGeoJSONFeature): BaseFeature | null {
  const fid = String(hit.id ?? hit.properties.fid ?? "");
  const kind = kindOf(fid);
  if (!kind) return null;
  const p = hit.properties;
  const str = (v: unknown) => (typeof v === "string" && v ? v : null);
  return {
    fid,
    kind,
    name: str(p.name) ?? (kind === "parcel" ? str(p.address) : null),
    use: kind === "park" ? "park" : kind === "parcel" ? "lot" : str(p.use),
    heightM: typeof p.height === "number" ? p.height : null,
    geometry: hit.geometry,
  };
}
