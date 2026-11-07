"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import { BUILDINGS_3D_LAYER, buildingAt, buildingsFilter, setSelectedState } from "@/lib/basemap";
import {
  buildStyle,
  CORNER_IMAGE,
  cornerImage,
  cornerPoints,
  PROPOSALS_SOURCE,
  proposalsCollection,
  REMOVED_SOURCE,
  SELECTION_CORNERS_SOURCE,
  SELECTION_SOURCE,
  toCollection,
} from "@/lib/map-style";
import { useMapStore } from "@/lib/store";
import { readMapTokens } from "@/lib/tokens";

import MapControls from "./map-controls";
import SelectionCard from "./selection-card";

/** Downtown, looking north-west along the street grid (rotated ~17° from north). */
export const INITIAL_VIEW = {
  center: [-79.3915, 43.6438] as [number, number],
  zoom: 15.4,
  pitch: 45,
  bearing: -17,
};

export default function MapView() {
  const container = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);

  useEffect(() => {
    let instance: MapLibreMap | null = null;
    let cancelled = false;

    void import("maplibre-gl").then(({ Map, setWorkerUrl }) => {
      if (cancelled || !container.current) return;
      // MapLibre looks for its worker next to its own file, which bundling breaks.
      setWorkerUrl(new URL("maplibre-gl/dist/maplibre-gl-worker.mjs", import.meta.url).href);
      const tokens = readMapTokens();
      instance = new Map({
        container: container.current,
        style: buildStyle(tokens),
        ...INITIAL_VIEW,
        maxPitch: 70,
        attributionControl: false,
      });
      const m = instance;
      m.on("load", () => {
        m.addImage(CORNER_IMAGE, cornerImage(tokens));
        setMap(m);
      });
      m.on("click", (e) => useMapStore.getState().select(buildingAt(m, e.point)));
      m.on("mouseenter", BUILDINGS_3D_LAYER, () => (m.getCanvas().style.cursor = "pointer"));
      m.on("mouseleave", BUILDINGS_3D_LAYER, () => (m.getCanvas().style.cursor = ""));
    });

    return () => {
      cancelled = true;
      instance?.remove();
    };
  }, []);

  useEffect(() => {
    if (!map) return;
    const source = (id: string) => map.getSource<GeoJSONSource>(id);

    const sync = (
      state: ReturnType<typeof useMapStore.getState>,
      prev?: ReturnType<typeof useMapStore.getState>,
    ) => {
      if (state.selected !== prev?.selected) {
        if (prev?.selected) setSelectedState(map, prev.selected, false);
        const feature = state.selected ? state.features[state.selected] : null;
        if (feature) setSelectedState(map, feature.fid, true);
        source(SELECTION_SOURCE)?.setData(toCollection(feature ? [feature.footprint] : []));
        source(SELECTION_CORNERS_SOURCE)?.setData(
          feature ? cornerPoints(feature, map.getBearing()) : toCollection([]),
        );
      }
      if (state.removed !== prev?.removed) {
        map.setFilter(BUILDINGS_3D_LAYER, buildingsFilter(state.removed));
        const footprints = state.removed.flatMap((fid) => state.features[fid]?.footprint ?? []);
        source(REMOVED_SOURCE)?.setData(toCollection(footprints));
      }
      if (state.proposals !== prev?.proposals) {
        source(PROPOSALS_SOURCE)?.setData(proposalsCollection(state.proposals));
      }
    };

    sync(useMapStore.getState());
    return useMapStore.subscribe(sync);
  }, [map]);

  return (
    <div className="absolute inset-0">
      {/* maplibre-gl.css makes this position: relative, so size it explicitly. */}
      <div ref={container} className="h-full w-full" />
      {map && (
        <>
          <SelectionCard map={map} />
          <MapControls map={map} />
        </>
      )}
    </div>
  );
}
