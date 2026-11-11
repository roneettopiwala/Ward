"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import type { GeoJSONSource, Map as MapLibreMap, MapMouseEvent } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import { fetchCatalog } from "@/lib/api";

import {
  BUILDINGS_3D_LAYER,
  buildingsFilter,
  highlightOverlay,
  setSelectedState,
} from "@/lib/basemap";
import {
  buildStyle,
  CORNER_IMAGE,
  cornerImage,
  cornerPoints,
  IMPACT_SOURCE,
  impactArea,
  PERSONA_PINS_LAYER,
  PERSONAS_SOURCE,
  personasCollection,
  PROPOSALS_SOURCE,
  proposalsCollection,
  REMOVED_SOURCE,
  SELECTION_CORNERS_SOURCE,
  SELECTION_HIGHLIGHT_SOURCE,
  SELECTION_SOURCE,
  toCollection,
} from "@/lib/map-style";
import { catalogMap, largestRadius } from "@/lib/parts";
import { selectAt } from "@/lib/selection";
import { type Draft, useMapStore } from "@/lib/store";
import { type MapTokens, readMapTokens } from "@/lib/tokens";
import type { Geometry, Proposal } from "@/lib/types";

import MapControls from "./map-controls";
import PersonaPins from "./persona-pins";
import PreviewCard from "./preview-card";
import PromptBar from "./prompt-bar";
import ResultsPanel from "./results-panel";
import SelectionCard from "./selection-card";

type State = ReturnType<typeof useMapStore.getState>;

/** The draft as a proposal, so the map can preview it with the same styling. */
function draftProposal(state: State, draft: Draft): Proposal | null {
  const feature = state.features[draft.fid];
  if (!feature) return null;
  return {
    id: "draft",
    parts: draft.parts,
    geometry: feature.footprint,
    replaces: [draft.fid],
    prompt: draft.prompt,
    assumptions: draft.assumptions,
    parentId: draft.parentId,
    version: 0,
  };
}

/** What the impact ring surrounds: the draft being set up, else the open proposal. */
function impactTarget(state: State): { geometry: Geometry; radiusM: number } | null {
  const proposal = state.draft
    ? draftProposal(state, state.draft)
    : state.proposals.find((p) => p.id === state.activeProposal);
  const radiusM = proposal && largestRadius(proposal.parts, catalogMap(state.catalog));
  return proposal && radiusM ? { geometry: proposal.geometry, radiusM } : null;
}

/** Downtown, looking north-west along the street grid (rotated ~17° from north). */
export const INITIAL_VIEW = {
  center: [-79.3915, 43.6438] as [number, number],
  zoom: 15.4,
  pitch: 45,
  bearing: -17,
};

export default function MapView() {
  const container = useRef<HTMLDivElement>(null);
  const tokens = useRef<MapTokens | null>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);

  useEffect(() => {
    fetchCatalog()
      .then((catalog) => useMapStore.getState().setCatalog(catalog))
      .catch(() => console.warn("Couldn't load the type catalog; is the API running?"));
  }, []);

  useEffect(() => {
    let instance: MapLibreMap | null = null;
    let cancelled = false;

    void import("maplibre-gl").then(({ Map, setWorkerUrl }) => {
      if (cancelled || !container.current) return;
      // MapLibre looks for its worker next to its own file, which bundling breaks.
      setWorkerUrl(new URL("maplibre-gl/dist/maplibre-gl-worker.mjs", import.meta.url).href);
      const t = readMapTokens();
      tokens.current = t;
      instance = new Map({
        container: container.current,
        style: buildStyle(t),
        ...INITIAL_VIEW,
        maxPitch: 70,
        attributionControl: false,
      });
      const m = instance;
      m.on("load", () => {
        m.addImage(CORNER_IMAGE, cornerImage(t));
        setMap(m);
      });
      m.on("click", (e: MapMouseEvent) => {
        // A persona pin opens that persona's card instead of selecting a building.
        const pin = m.queryRenderedFeatures(e.point, { layers: [PERSONA_PINS_LAYER] })[0];
        if (pin) useMapStore.getState().focusPersona(String(pin.properties.id));
        else void selectAt(m, e.point);
      });
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

    const sync = (state: State, prev?: State) => {
      if (state.selected !== prev?.selected) {
        if (prev?.selected) setSelectedState(map, prev.selected, false);
        const feature = state.selected ? state.features[state.selected] : null;
        if (feature) setSelectedState(map, feature.fid, true);
        source(SELECTION_SOURCE)?.setData(toCollection(feature ? [feature.footprint] : []));
        const overlay = feature ? highlightOverlay(feature.fid) : null;
        source(SELECTION_HIGHLIGHT_SOURCE)?.setData({
          type: "FeatureCollection",
          features: overlay
            ? [{ type: "Feature", properties: { height: overlay.heightM }, geometry: overlay.footprint }]
            : [],
        });
        source(SELECTION_CORNERS_SOURCE)?.setData(
          feature ? cornerPoints(feature, map.getBearing()) : toCollection([]),
        );
      }
      if (state.removed !== prev?.removed || state.draft?.fid !== prev?.draft?.fid) {
        // A building being replaced in the picker is hidden while its preview shows.
        const hidden = state.draft ? [...state.removed, state.draft.fid] : state.removed;
        map.setFilter(BUILDINGS_3D_LAYER, buildingsFilter(hidden));
        const footprints = state.removed.flatMap((fid) => state.features[fid]?.footprint ?? []);
        source(REMOVED_SOURCE)?.setData(toCollection(footprints));
      }
      if (
        state.proposals !== prev?.proposals ||
        state.draft !== prev?.draft ||
        state.catalog !== prev?.catalog
      ) {
        const draft = state.draft && draftProposal(state, state.draft);
        // A draft that changes a proposal is previewed in its place.
        const kept = state.proposals.filter((p) => p.id !== draft?.parentId);
        const shown = draft ? [...kept, draft] : state.proposals;
        if (tokens.current) {
          source(PROPOSALS_SOURCE)?.setData(proposalsCollection(shown, state.catalog, tokens.current));
        }
      }
      if (
        state.draft !== prev?.draft ||
        state.activeProposal !== prev?.activeProposal ||
        state.proposals !== prev?.proposals ||
        state.catalog !== prev?.catalog
      ) {
        const target = impactTarget(state);
        source(IMPACT_SOURCE)?.setData(
          target ? impactArea(target.geometry, target.radiusM) : toCollection([]),
        );
      }

      const cards = (s: State | undefined) =>
        s?.activeProposal ? s.analyses[s.activeProposal]?.personas : undefined;
      if (cards(state) !== cards(prev) || state.focusedPersona !== prev?.focusedPersona) {
        source(PERSONAS_SOURCE)?.setData(personasCollection(cards(state) ?? [], state.focusedPersona));
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
          <PersonaPins map={map} />
          <ResultsPanel />
          <PreviewCard />
          <PromptBar />
        </>
      )}
    </div>
  );
}
