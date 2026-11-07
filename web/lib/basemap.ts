/**
 * OpenFreeMap / OpenMapTiles adapter.
 *
 * This is the only module that knows the basemap's source layers and feature
 * ids. Everything else works with Ward fids ("building:<id>"). Phase 6 swaps
 * this for our own PMTiles with our own fids.
 */
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
const FONT = ["Noto Sans Regular"];

export const basemapSource: SourceSpecification = {
  type: "vector",
  url: "https://tiles.openfreemap.org/planet",
  attribution: "© OpenFreeMap © OpenMapTiles © OpenStreetMap contributors",
};

export const basemapGlyphs = "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf";

export const basemapAttribution =
  "Basemap: © OpenFreeMap · © OpenMapTiles · © OpenStreetMap contributors";

/** Basemap ids that make up each Ward fid the user has selected. */
const sourceIdsByFid = new Map<Fid, number[]>();

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
  const hidden = hiddenFids.flatMap((fid) => sourceIdsByFid.get(fid) ?? []);
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
  for (const id of sourceIdsByFid.get(fid) ?? []) {
    map.setFeatureState({ source: BASEMAP_SOURCE, sourceLayer: "building", id }, { selected });
  }
}

/** The building under a screen point, grouped into one whole building. */
export function buildingAt(map: MapLibreMap, point: PointLike): BaseFeature | null {
  const hit = map.queryRenderedFeatures(point, { layers: [BUILDINGS_3D_LAYER] })[0];
  // A merged low-zoom shape is not one building; the user has to zoom in.
  if (hit?.id === undefined || hit.properties.render_height === undefined) return null;

  // Buildings mapped as parts have a hide_3d outline around them; select that.
  const ground = map.project(pointOnFeature(hit).geometry.coordinates as [number, number]);
  const outline = map
    .queryRenderedFeatures(ground, { layers: [BUILDING_FOOTPRINT_LAYER] })
    .find((f) => f.properties.hide_3d === true);
  const rootId = Number(outline?.id ?? hit.id);

  const everyFootprint = map.queryRenderedFeatures({ layers: [BUILDING_FOOTPRINT_LAYER] });
  const footprint = mergePieces(everyFootprint.filter((f) => f.id === rootId));
  if (!footprint) return null;

  const members = outline
    ? everyFootprint.filter(
        (f) =>
          f.properties.hide_3d !== true && booleanPointInPolygon(pointOnFeature(f), footprint),
      )
    : [];
  const ids = [...new Set([rootId, ...members.map((f) => Number(f.id))])];

  const heights = [hit, ...members].map((f) => Number(f.properties.render_height ?? 0));
  const poi = poiFor(map, rootId, footprint);
  const fid = `building:${rootId}`;
  sourceIdsByFid.set(fid, ids);

  return {
    fid,
    name: poi ? String(poi.properties.name) : null,
    use: poi ? humanize(String(poi.properties.subclass ?? poi.properties.class)) : null,
    heightM: Math.max(...heights) || null,
    footprint,
  };
}

/** Tiles clip features at their edges; stitch the pieces back together. */
function mergePieces(pieces: MapGeoJSONFeature[]): Polygon | MultiPolygon | null {
  const polys = pieces
    .map((f) => f.geometry)
    .filter((g): g is Polygon | MultiPolygon => g.type === "Polygon" || g.type === "MultiPolygon")
    .map((geometry): Feature<Polygon | MultiPolygon> => ({ type: "Feature", properties: {}, geometry }));
  if (polys.length === 0) return null;
  if (polys.length === 1) return polys[0].geometry;
  return union(featureCollection(polys))?.geometry ?? polys[0].geometry;
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
