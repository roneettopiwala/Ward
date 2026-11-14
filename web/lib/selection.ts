import type { Map as MapLibreMap } from "maplibre-gl";

import { featureDetail } from "./api";
import { featuresAt } from "./city-layers";
import { useMapStore } from "./store";
import type { BaseFeature } from "./types";

/**
 * Select what's under a click: the top feature by priority (buildings, points,
 * lines, parks, parcels). Anything else there is offered as "Also here".
 */
export async function selectAt(map: MapLibreMap, point: { x: number; y: number }): Promise<void> {
  const [top, ...others] = featuresAt(map, point);
  if (!top) {
    useMapStore.getState().select(null);
    return;
  }
  await selectFeature(top, others);
}

/**
 * Show the tile's version of a feature straight away, then swap in the full
 * one (whole geometry, zoning, nearby transit) from the API.
 */
export async function selectFeature(pending: BaseFeature, alsoHere: BaseFeature[]): Promise<void> {
  const { select, resolve } = useMapStore.getState();
  select(pending, "loading", alsoHere);
  try {
    const feature = await featureDetail(pending.fid);
    resolve(pending.fid, feature ?? pending, feature ? "ready" : "not-found");
  } catch {
    resolve(pending.fid, pending, "error");
  }
}
