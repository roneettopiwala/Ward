/**
 * OpenFreeMap / OpenMapTiles adapter.
 *
 * This is the only module that knows the basemap's source layers and feature
 * ids. Everything else works with Ward fids ("building:<id>"). Phase 6 swaps
 * this for our own PMTiles with our own fids.
 */
import booleanIntersects from "@turf/boolean-intersects";
import booleanPointInPolygon from "@turf/boolean-point-in-polygon";
import { featureCollection } from "@turf/helpers";
import pointOnFeature from "@turf/point-on-feature";
import union from "@turf/union";
import type { Feature, MultiPolygon, Polygon } from "geojson";
import type {
  ExpressionSpecification,
  LayerSpecification,
  Map as MapLibreMap,
  MapGeoJSONFeature,
  PointLike,
  SourceSpecification,
} from "maplibre-gl";

import type { MapTokens } from "./tokens";
import type { BaseFeature, Fid } from "./types";

export const BASEMAP_SOURCE = "openmaptiles";
export const BUILDINGS_3D_LAYER = "buildings-3d";

const BUILDING_FOOTPRINT_LAYER = "buildings-footprint";
const POI_HIT_LAYER = "poi-hit";
export const FONT = ["Noto Sans Regular"];

export const basemapSource: SourceSpecification = {
  type: "vector",
  url: "https://tiles.openfreemap.org/planet",
  attribution: "© OpenFreeMap © OpenMapTiles © OpenStreetMap contributors",
};

export const basemapGlyphs = "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf";

export const basemapAttribution =
  "Basemap: © OpenFreeMap · © OpenMapTiles · © OpenStreetMap contributors";

/**
 * What each selected fid means in basemap terms: the basemap ids to highlight
 * and hide, or for a part of a merged shape, that part's own geometry.
 */
const registry = new Map<
  Fid,
  { ids: number[]; merged: Polygon | MultiPolygon | null; heightM: number }
>();

const roadClasses = ["motorway", "trunk", "primary", "secondary", "tertiary", "minor", "service"];

/** Layers drawn below Ward's overlays. */
export function basemapLayers(t: MapTokens): LayerSpecification[] {
  return [
    { id: "ground", type: "background", paint: { "background-color": t.ground } },
    {
      id: "park",
      type: "fill",
      source: BASEMAP_SOURCE,
      "source-layer": "park",
      paint: { "fill-color": t.park },
    },
    {
      id: "landcover-green",
      type: "fill",
      source: BASEMAP_SOURCE,
      "source-layer": "landcover",
      filter: ["in", ["get", "class"], ["literal", ["grass", "wood"]]],
      paint: { "fill-color": t.park },
    },
    {
      id: "water",
      type: "fill",
      source: BASEMAP_SOURCE,
      "source-layer": "water",
      paint: { "fill-color": t.water },
    },
    {
      id: "roads",
      type: "line",
      source: BASEMAP_SOURCE,
      "source-layer": "transportation",
      filter: ["in", ["get", "class"], ["literal", roadClasses]],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": t.road,
        "line-width": ["interpolate", ["exponential", 1.6], ["zoom"], 12, 1, 16, 10, 19, 40],
      },
    },
    // Invisible: lets clicks find whole-building outlines, including the
    // hide_3d outlines that only exist to group building parts.
    {
      id: BUILDING_FOOTPRINT_LAYER,
      type: "fill",
      source: BASEMAP_SOURCE,
      "source-layer": "building",
      paint: { "fill-opacity": 0 },
    },
    {
      id: POI_HIT_LAYER,
      type: "circle",
      source: BASEMAP_SOURCE,
      "source-layer": "poi",
      filter: ["has", "name"],
      paint: { "circle-opacity": 0, "circle-radius": 1 },
    },
  ];
}

/** 3D buildings, minus anything whose fid is hidden. */
export function buildingsLayer(t: MapTokens, hiddenFids: Fid[]): LayerSpecification {
  return {
    id: BUILDINGS_3D_LAYER,
    type: "fill-extrusion",
    source: BASEMAP_SOURCE,
    "source-layer": "building",
    filter: buildingsFilter(hiddenFids),
    paint: {
      "fill-extrusion-color": [
        "case",
        ["boolean", ["feature-state", "selected"], false],
        t.buildingSelected,
        t.building,
      ],
      "fill-extrusion-height": ["coalesce", ["get", "render_height"], 0],
      "fill-extrusion-base": ["coalesce", ["get", "render_min_height"], 0],
      "fill-extrusion-opacity": 1,
    },
  };
}

export function buildingsFilter(hiddenFids: Fid[]): ExpressionSpecification {
  const hidden = hiddenFids.flatMap((fid) => registry.get(fid)?.ids ?? []);
  return [
    "all",
    ["!=", ["get", "hide_3d"], true],
    // Merged low-zoom shapes reuse one building's id; never hide those.
    ["any", ["!", isRealBuilding], ["!", ["in", ["id"], ["literal", hidden]]]],
  ];
}

/**
 * Below tile zoom 14, OpenFreeMap merges every building in a tile into one
 * shape (no height, one borrowed id). Only z14 features are real buildings.
 */
const isRealBuilding: ExpressionSpecification = ["has", "render_height"];

/** Labels drawn above everything else. */
export function labelLayers(t: MapTokens): LayerSpecification[] {
  return [
    {
      id: "road-labels",
      type: "symbol",
      source: BASEMAP_SOURCE,
      "source-layer": "transportation_name",
      minzoom: 14,
      filter: ["has", "name"],
      layout: {
        "symbol-placement": "line",
        "text-field": ["upcase", ["get", "name"]],
        "text-font": FONT,
        "text-size": 10,
        "text-letter-spacing": 0.3,
      },
      paint: { "text-color": t.label },
    },
    {
      id: "water-labels",
      type: "symbol",
      source: BASEMAP_SOURCE,
      "source-layer": "water_name",
      layout: {
        "text-field": ["upcase", ["get", "name"]],
        "text-font": FONT,
        "text-size": 12,
        "text-letter-spacing": 0.6,
      },
      paint: { "text-color": t.label },
    },
  ];
}

/** Set or clear the highlight on every basemap feature behind a fid. */
export function setSelectedState(map: MapLibreMap, fid: Fid, selected: boolean): void {
  for (const id of registry.get(fid)?.ids ?? []) {
    map.setFeatureState({ source: BASEMAP_SOURCE, sourceLayer: "building", id }, { selected });
  }
}

/**
 * For buildings the basemap merged with others, feature-state would light up
 * every building in the merge, so the map draws this overlay instead.
 */
export function highlightOverlay(
  fid: Fid,
): { footprint: Polygon | MultiPolygon; heightM: number } | null {
  const entry = registry.get(fid);
  return entry?.merged ? { footprint: entry.merged, heightM: entry.heightM } : null;
}

/** Point a Ward fid (e.g. from our database) at the basemap features of a click. */
export function linkFid(fid: Fid, basemapFid: Fid): void {
  const entry = registry.get(basemapFid);
  if (entry) registry.set(fid, entry);
}

export type BasemapHit = {
  feature: BaseFeature;
  /** A point on the ground inside the clicked building, for matching to our data. */
  ground: [number, number];
};

/** The building under a screen point, grouped into one whole building. */
export function buildingAt(map: MapLibreMap, point: PointLike): BasemapHit | null {
  const hit = map.queryRenderedFeatures(point, { layers: [BUILDINGS_3D_LAYER] })[0];
  // A merged low-zoom shape is not one building; the user has to zoom in.
  if (hit?.id === undefined || hit.properties.render_height === undefined) return null;

  const clicked = map.unproject(point);
  const click: [number, number] = [clicked.lng, clicked.lat];
  const hitPart = nearestPart(polygonsOf([hit]), click);

  // Buildings mapped as parts have a hide_3d outline around them; select that.
  const ground = map.project(pointOnFeature(hitPart).geometry.coordinates as [number, number]);
  const outline = map
    .queryRenderedFeatures(ground, { layers: [BUILDING_FOOTPRINT_LAYER] })
    .find((f) => f.properties.hide_3d === true);
  const rootId = Number(outline?.id ?? hit.id);

  const everyFootprint = map
    .queryRenderedFeatures({ layers: [BUILDING_FOOTPRINT_LAYER] })
    .filter((f) => f.properties.render_height !== undefined);

  // OpenFreeMap merges same-height buildings into one feature, and reuses ids
  // across tiles. Keep only the pieces connected to the one that was clicked.
  const sameId = polygonsOf(everyFootprint.filter((f) => f.id === rootId));
  const seed = outline ? nearestPart(sameId, click) : hitPart;
  const piecesOfBuilding = connected(seed, sameId);
  const footprint = mergePolygons(piecesOfBuilding);

  const members = outline
    ? everyFootprint.filter(
        (f) =>
          f.properties.hide_3d !== true && booleanPointInPolygon(pointOnFeature(f), footprint),
      )
    : [];
  const heights = [hit, ...members].map((f) => Number(f.properties.render_height ?? 0));
  const heightM = Math.max(...heights);

  // Basemap ids are only safe to highlight and hide when they mean this building alone.
  const ids = [rootId, ...members.map((f) => Number(f.id))];
  const exclusive =
    piecesOfBuilding.length === sameId.length &&
    members.every((m) =>
      polygonsOf(everyFootprint.filter((f) => f.id === m.id)).every((p) =>
        booleanPointInPolygon(pointOnFeature(p), footprint),
      ),
    );

  const poi = poiFor(map, rootId, footprint);
  const fid = exclusive ? `basemap:${rootId}` : `basemap:${rootId}@${click.join(",")}`;
  registry.set(fid, exclusive
    ? { ids: [...new Set(ids)], merged: null, heightM }
    : { ids: [], merged: footprint, heightM });

  return {
    feature: {
      fid,
      name: exclusive && poi ? String(poi.properties.name) : null,
      use: exclusive && poi ? humanize(String(poi.properties.subclass ?? poi.properties.class)) : null,
      heightM: heightM || null,
      footprint,
    },
    ground: pointOnFeature(footprint).geometry.coordinates as [number, number],
  };
}

function polygonsOf(features: MapGeoJSONFeature[]): Polygon[] {
  return features.flatMap((f): Polygon[] => {
    if (f.geometry.type === "Polygon") return [f.geometry];
    if (f.geometry.type === "MultiPolygon") {
      return f.geometry.coordinates.map((coordinates) => ({ type: "Polygon", coordinates }));
    }
    return [];
  });
}

function nearestPart(parts: Polygon[], [lng, lat]: [number, number]): Polygon {
  const inside = parts.find((p) => booleanPointInPolygon([lng, lat], p));
  if (inside) return inside;
  const dist = (p: Polygon) => {
    const [x, y] = pointOnFeature(p).geometry.coordinates;
    return (x - lng) ** 2 + (y - lat) ** 2;
  };
  return parts.reduce((best, p) => (dist(p) < dist(best) ? p : best));
}

/** The seed plus every piece touching it, directly or through other pieces. */
function connected(seed: Polygon, pieces: Polygon[]): Polygon[] {
  const group = [seed];
  let rest = pieces.filter((p) => p !== seed && !samePolygon(p, seed));
  for (let grew = true; grew; ) {
    grew = false;
    for (const p of rest) {
      if (group.some((g) => booleanIntersects(g, p))) {
        group.push(p);
        grew = true;
      }
    }
    rest = rest.filter((p) => !group.includes(p));
  }
  return group;
}

function samePolygon(a: Polygon, b: Polygon): boolean {
  return JSON.stringify(a.coordinates) === JSON.stringify(b.coordinates);
}

/** Tiles clip features at their edges; stitch the pieces back together. */
function mergePolygons(polys: Polygon[]): Polygon | MultiPolygon {
  if (polys.length === 1) return polys[0];
  const features = polys.map((geometry): Feature<Polygon> => ({ type: "Feature", properties: {}, geometry }));
  return union(featureCollection(features))?.geometry ?? polys[0];
}

/** A named POI for the building: same OSM id first, else the best-ranked one inside. */
function poiFor(
  map: MapLibreMap,
  rootId: number,
  footprint: Polygon | MultiPolygon,
): MapGeoJSONFeature | null {
  const pois = map.queryRenderedFeatures({ layers: [POI_HIT_LAYER] });
  const sameId = pois.find((p) => Number(p.id) === rootId);
  if (sameId) return sameId;
  const inside = pois
    .filter((p) => p.geometry.type === "Point" && booleanPointInPolygon(p.geometry.coordinates, footprint))
    .sort((a, b) => Number(a.properties.rank ?? 99) - Number(b.properties.rank ?? 99));
  return inside[0] ?? null;
}

function humanize(value: string): string {
  const words = value.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
