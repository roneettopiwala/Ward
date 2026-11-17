import { create } from "zustand";

import { catalogMap, defaultParams, insertPart } from "./parts";
import type { ShapeCheck } from "./api";
import type {
  Analysis,
  BaseFeature,
  CatalogType,
  Fid,
  Geometry,
  Part,
  Proposal,
  SelectionStatus,
} from "./types";

export type Tool = "select" | "area" | "line" | "point";
export type AreaTool = "lot" | "rectangle" | "polygon" | "freehand";

/** A shape being drawn, before it becomes a site to build on. */
export type Drawing = {
  areaTool: AreaTool;
  /** The shape so far: polygon, routed line or point. Null before the first click. */
  geometry: Geometry | null;
  /** Corners placed (areas) or waypoints clicked (lines). */
  points: number;
  /** The shape is complete and can still be adjusted; Finish shape checks it. */
  complete: boolean;
  /** Streets a routed line follows. */
  streets: string[];
  busy: boolean;
  error: string | null;
  /** The server's check, once Finish shape is pressed. */
  check: ShapeCheck | null;
};

const emptyDrawing = (areaTool: AreaTool = "polygon"): Drawing => ({
  areaTool,
  geometry: null,
  points: 0,
  complete: false,
  streets: [],
  busy: false,
  error: null,
  check: null,
});

/** The base features a proposal on this site replaces. */
export function replacesOf(feature: BaseFeature): Fid[] {
  return feature.drawn ? feature.drawn.replaces : [feature.fid];
}

/** The edit overlay: base data minus `removed`, plus `proposals`. */
type Edits = {
  removed: Fid[];
  proposals: Proposal[];
};

/** A proposal being previewed before analysis: parsed from a prompt or edited by hand. */
export type Draft = {
  /** The site: the selected building it replaces. */
  fid: Fid;
  parts: Part[];
  prompt: string | null;
  assumptions: string[];
  replacesExisting: boolean;
  /** The proposal this draft changes (Edit or Refine), if any. */
  parentId: string | null;
};

type MapState = Edits & {
  selected: Fid | null;
  selectionStatus: SelectionStatus;
  /** Every base feature the user has selected, kept for outlines and geometry. */
  features: Record<Fid, BaseFeature>;
  /** Other features under the click that made the selection, for switching to. */
  alsoHere: BaseFeature[];
  /** Snapshots of the edits before each action, newest last. */
  history: Edits[];
  catalog: CatalogType[];
  draft: Draft | null;
  /** Analysis per proposal id, and the one the results panel shows. */
  analyses: Record<string, Analysis>;
  activeProposal: string | null;
  /** The persona picked from a map pin or card, highlighted in both. */
  focusedPersona: string | null;
  /** Text in the prompt bar (set from outside by "Edit prompt"). */
  promptText: string;
  tool: Tool;
  drawing: Drawing;

  select: (feature: BaseFeature | null, status?: SelectionStatus, alsoHere?: BaseFeature[]) => void;
  /** Swap a pending selection for what it resolved to, if it is still selected. */
  resolve: (pendingFid: Fid, feature: BaseFeature, status: SelectionStatus) => void;
  remove: (fid: Fid) => void;
  setCatalog: (catalog: CatalogType[]) => void;
  setDraft: (draft: Draft | null) => void;
  /** Open a proposal's parts in the preview card to change them (Edit). */
  editProposal: (proposalId: string) => void;
  setPartParam: (index: number, name: string, value: number) => void;
  setPartType: (index: number, type: string) => void;
  addPart: (type: string) => void;
  removePart: (index: number) => void;
  /** Commit the draft as a proposal (a new version when it has a parent); returns it. */
  commitDraft: () => Proposal | null;
  updateAnalysis: (proposalId: string, patch: Partial<Analysis>) => void;
  closePanel: () => void;
  focusPersona: (personaId: string | null) => void;
  setPromptText: (text: string) => void;
  undo: () => void;
  /** Pick a tool; drawing tools start a fresh shape. */
  setTool: (tool: Tool, areaTool?: AreaTool) => void;
  patchDrawing: (patch: Partial<Drawing>) => void;
  /** Turn the finished shape into a site and select it. */
  finishDrawing: (site: BaseFeature) => void;
};

const snapshot = ({ removed, proposals }: Edits): Edits => ({ removed, proposals });

export const useMapStore = create<MapState>()((set, get) => {
  /** Apply a change to the draft's parts. */
  const editParts = (change: (parts: Part[], s: MapState) => Part[]) =>
    set((s) => (s.draft ? { draft: { ...s.draft, parts: change(s.draft.parts, s) } } : {}));

  return {
    selected: null,
    selectionStatus: "ready",
    features: {},
    alsoHere: [],
    removed: [],
    proposals: [],
    history: [],
    catalog: [],
    draft: null,
    analyses: {},
    activeProposal: null,
    focusedPersona: null,
    promptText: "",
    tool: "select",
    drawing: emptyDrawing(),

    select: (feature, status = "ready", alsoHere = []) =>
      set((s) =>
        feature
          ? {
              selected: feature.fid,
              selectionStatus: status,
              features: { ...s.features, [feature.fid]: feature },
              alsoHere,
              draft: null,
            }
          : { selected: null, alsoHere: [], draft: null },
      ),

    resolve: (pendingFid, feature, status) =>
      set((s) =>
        s.selected === pendingFid
          ? {
              selected: feature.fid,
              selectionStatus: status,
              features: { ...s.features, [feature.fid]: feature },
            }
          : {},
      ),

    remove: (fid) =>
      set((s) => {
        if (s.removed.includes(fid)) return {};
        return {
          history: [...s.history, snapshot(s)],
          removed: [...s.removed, fid],
          selected: null,
          draft: null,
        };
      }),

    setCatalog: (catalog) => set({ catalog }),

    setDraft: (draft) => set({ draft }),

    editProposal: (proposalId) =>
      set((s) => {
        const p = s.proposals.find((x) => x.id === proposalId);
        if (!p) return {};
        return {
          draft: {
            fid: p.siteFid,
            parts: p.parts,
            prompt: null,
            assumptions: [],
            replacesExisting: true,
            parentId: p.id,
          },
        };
      }),

    setPartParam: (index, name, value) =>
      editParts((parts) =>
        parts.map((p, i) => (i === index ? { ...p, params: { ...p.params, [name]: value } } : p)),
      ),

    setPartType: (index, type) =>
      editParts((parts, s) => {
        const t = s.catalog.find((c) => c.type === type);
        if (!t) return parts;
        // A new type starts from its own defaults; tags described the old type.
        const replaced = { type, params: defaultParams(t), tags: [] };
        if (parts.length === 1) return [replaced];
        return insertPart(
          parts.filter((_, i) => i !== index),
          replaced,
          catalogMap(s.catalog),
        );
      }),

    addPart: (type) =>
      editParts((parts, s) => {
        const t = s.catalog.find((c) => c.type === type);
        if (!t) return parts;
        return insertPart(parts, { type, params: defaultParams(t), tags: [] }, catalogMap(s.catalog));
      }),

    removePart: (index) =>
      editParts((parts) => (parts.length > 1 ? parts.filter((_, i) => i !== index) : parts)),

    commitDraft: () => {
      const s = get();
      const draft = s.draft;
      const feature = draft ? s.features[draft.fid] : null;
      if (!draft || !feature) return null;
      const parent = draft.parentId ? s.proposals.find((p) => p.id === draft.parentId) : undefined;
      const proposal: Proposal = {
        id: crypto.randomUUID(),
        parts: draft.parts,
        geometry: feature.geometry,
        siteFid: feature.fid,
        replaces: replacesOf(feature),
        prompt: draft.prompt,
        assumptions: draft.assumptions,
        parentId: parent?.id ?? null,
        version: parent ? parent.version + 1 : 1,
      };
      set({
        history: [...s.history, snapshot(s)],
        removed: [...new Set([...s.removed, ...replacesOf(feature)])],
        // A new version takes its parent's place on the map.
        proposals: parent
          ? s.proposals.map((p) => (p.id === parent.id ? proposal : p))
          : [...s.proposals, proposal],
        selected: null,
        draft: null,
        analyses: { ...s.analyses, [proposal.id]: { status: "creating" } },
        activeProposal: proposal.id,
        focusedPersona: null,
      });
      return proposal;
    },

    updateAnalysis: (proposalId, patch) =>
      set((s) => ({
        analyses: { ...s.analyses, [proposalId]: { ...s.analyses[proposalId], ...patch } },
      })),

    closePanel: () => set({ activeProposal: null, focusedPersona: null, draft: null }),

    focusPersona: (focusedPersona) => set({ focusedPersona }),

    setPromptText: (promptText) => set({ promptText }),

    setTool: (tool, areaTool) =>
      set((s) => ({
        tool,
        drawing: emptyDrawing(areaTool ?? s.drawing.areaTool),
        ...(tool === "select" ? {} : { selected: null, alsoHere: [], draft: null }),
      })),

    patchDrawing: (patch) => set((s) => ({ drawing: { ...s.drawing, ...patch } })),

    finishDrawing: (site) =>
      set((s) => ({
        tool: "select",
        drawing: emptyDrawing(s.drawing.areaTool),
        selected: site.fid,
        selectionStatus: "ready",
        features: { ...s.features, [site.fid]: site },
        alsoHere: [],
        draft: null,
      })),

    undo: () =>
      set((s) => {
        const previous = s.history.at(-1);
        if (!previous) return {};
        const has = (id: string | null | undefined): id is string =>
          !!id && previous.proposals.some((p) => p.id === id);
        // Undoing a new version goes back to the version it changed.
        const parentId = s.proposals.find((p) => p.id === s.activeProposal)?.parentId;
        const active = has(s.activeProposal) ? s.activeProposal : has(parentId) ? parentId : null;
        return {
          ...previous,
          history: s.history.slice(0, -1),
          selected: null,
          draft: null,
          activeProposal: active,
          focusedPersona: active === s.activeProposal ? s.focusedPersona : null,
        };
      }),
  };
});
