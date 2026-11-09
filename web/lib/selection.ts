import type { Map as MapLibreMap, PointLike } from "maplibre-gl";

import { featureAt, featureDetail } from "./api";
import { buildingAt, linkFid } from "./basemap";
import { useMapStore } from "./store";

/**
 * Select the building under a click: show the basemap's version straight
 * away, then swap in ours from the API once the location is matched.
 */
export async function selectAt(map: MapLibreMap, point: PointLike): Promise<void> {
  const { select, resolve } = useMapStore.getState();
  const hit = buildingAt(map, point);
  if (!hit) {
    select(null);
    return;
  }
  const pending = hit.feature;
  select(pending, "loading");

  try {
    const match = await featureAt(hit.ground);
    if ("missing" in match) {
      resolve(pending.fid, pending, match.missing === "outside_area" ? "outside-area" : "not-found");
      return;
    }
    const feature = await featureDetail(match.fid);
    linkFid(feature.fid, pending.fid);
    resolve(pending.fid, feature, "ready");
  } catch {
    resolve(pending.fid, pending, "error");
  }
}
