"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import type { GeoJSONSource, Map as MapLibreMap, MapMouseEvent } from "maplibre-gl";
import { Protocol } from "pmtiles";
import { useEffect, useRef, useState } from "react";

import { fetchCatalog } from "@/lib/api";
import { HIDEABLE_LAYERS, HIT_LAYERS, notHidden, setSelectedState } from "@/lib/city-layers";
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
  SELECTION_SOURCE,
  toCollection,
} from "@/lib/map-style";
import { catalogMap, largestRadius } from "@/lib/parts";
import { selectAt } from "@/lib/selection";
import { type Draft, replacesOf, useMapStore } from "@/lib/store";
import { type MapTokens, readMapTokens } from "@/lib/tokens";
import type { Geometry, Proposal } from "@/lib/types";

import { DrawController } from "@/lib/draw";

import DrawPanel, { DrawHints } from "./draw-panel";
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
    geometry: feature.geometry,
    siteFid: draft.fid,
    replaces: replacesOf(feature),
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

let pmtilesRegistered = false;

export default function MapView() {
  const container = useRef<HTMLDivElement>(null);
  const tokens = useRef<MapTokens | null>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [drawController, setDrawController] = useState<DrawController | null>(null);

  useEffect(() => {
    fetchCatalog()
      .then((catalog) => useMapStore.getState().setCatalog(catalog))
      .catch(() => console.warn("Couldn't load the type catalog; is the API running?"));
  }, []);

  useEffect(() => {
    let instance: MapLibreMap | null = null;
    let cancelled = false;

    void import("maplibre-gl").then(({ Map, addProtocol, setWorkerUrl }) => {
      if (cancelled || !container.current) return;
      // MapLibre looks for its worker next to its own file, which bundling breaks.
      setWorkerUrl(new URL("maplibre-gl/dist/maplibre-gl-worker.mjs", import.meta.url).href);
      if (!pmtilesRegistered) {
        addProtocol("pmtiles", new Protocol().tile);
        pmtilesRegistered = true;
      }
      const t = readMapTokens();
      tokens.current = t;
      instance = new Map({
        container: container.current,
        style: buildStyle(t, window.location.origin),
        ...INITIAL_VIEW,
        maxPitch: 70,
        attributionControl: false,
      });
      const m = instance;
      let controller: DrawController | null = null;
      m.on("load", () => {
        m.addImage(CORNER_IMAGE, cornerImage(t));
        controller = new DrawController(m, t);
        setDrawController(controller);
        setMap(m);
      });
      m.on("remove", () => controller?.dispose());
      m.on("dblclick", (e: MapMouseEvent) => controller?.handleDoubleClick(e));
      m.on("click", (e: MapMouseEvent) => {
        // While drawing, clicks belong to the shape.
        if (controller?.handleClick(e)) return;
        // A persona pin opens that persona's card instead of selecting a building.
        const pin = m.queryRenderedFeatures(e.point, { layers: [PERSONA_PINS_LAYER] })[0];
        if (pin) useMapStore.getState().focusPersona(String(pin.properties.id));
        else void selectAt(m, e.point);
      });
      const drawing = () => useMapStore.getState().tool !== "select";
      for (const layer of HIT_LAYERS) {
        m.on("mouseenter", layer, () => !drawing() && (m.getCanvas().style.cursor = "pointer"));
        m.on("mouseleave", layer, () => !drawing() && (m.getCanvas().style.cursor = ""));
      }
    });

    return () => {
      cancelled = true;
      instance?.remove();
    };
  }, []);

  // Backspace takes back the last corner or waypoint while drawing.
  useEffect(() => {
    if (!drawController) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === "Backspace" && useMapStore.getState().tool !== "select") {
        e.preventDefault();
        drawController.undoPoint();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawController]);

  useEffect(() => {
    if (!map) return;
    const source = (id: string) => map.getSource<GeoJSONSource>(id);

    const sync = (state: State, prev?: State) => {
      const selectedFeature = (s: State | undefined) => (s?.selected ? s.features[s.selected] : null);
      // Also redraw when the tile's clipped shape is swapped for the full one.
      if (selectedFeature(state) !== selectedFeature(prev)) {
        if (prev?.selected) setSelectedState(map, prev.selected, false);
        const feature = selectedFeature(state);
        if (feature) setSelectedState(map, feature.fid, true);
        source(SELECTION_SOURCE)?.setData(toCollection(feature ? [feature.geometry] : []));
        source(SELECTION_CORNERS_SOURCE)?.setData(
          feature ? cornerPoints(feature, map.getBearing()) : toCollection([]),
        );
      }
      if (state.removed !== prev?.removed || state.draft?.fid !== prev?.draft?.fid) {
        // A feature being replaced is hidden while its preview shows.
        const site = state.draft ? state.features[state.draft.fid] : undefined;
        const hidden = site ? [...state.removed, ...replacesOf(site)] : state.removed;
        for (const layer of HIDEABLE_LAYERS) map.setFilter(layer, notHidden(hidden));
        const outlines = state.removed.flatMap((fid) => state.features[fid]?.geometry ?? []);
        source(REMOVED_SOURCE)?.setData(toCollection(outlines));
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
          {drawController && <DrawPanel controller={drawController} />}
          <DrawHints />
        </>
      )}
    </div>
  );
}
