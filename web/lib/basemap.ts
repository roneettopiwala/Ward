/**
 * OpenFreeMap background: ground, water, green cover and place labels.
 *
 * Only scenery. Everything selectable (buildings, parcels, streets, parks,
 * cycling, transit) comes from our own tiles in city-layers.ts, with our fids.
 */
import type { LayerSpecification, SourceSpecification } from "maplibre-gl";

import type { MapTokens } from "./tokens";

export const BASEMAP_SOURCE = "openmaptiles";
export const FONT = ["Noto Sans Regular"];

export const basemapSource: SourceSpecification = {
  type: "vector",
  url: "https://tiles.openfreemap.org/planet",
  attribution: "© OpenFreeMap © OpenMapTiles © OpenStreetMap contributors",
};

export const basemapGlyphs = "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf";

export const basemapAttribution =
  "City data: © City of Toronto (Open Government Licence – Toronto) · Statistics Canada · " +
  "Basemap: © OpenFreeMap · © OpenMapTiles · © OpenStreetMap contributors";

/** Layers drawn below everything else. */
export function basemapLayers(t: MapTokens): LayerSpecification[] {
  return [
    { id: "ground", type: "background", paint: { "background-color": t.ground } },
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
  ];
}

/** Labels drawn above the map's features. */
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
