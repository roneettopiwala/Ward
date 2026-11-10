import { create } from "zustand";

import type {
  Analysis,
  BaseFeature,
  CatalogType,
  Fid,
  Proposal,
  SelectionStatus,
} from "./types";

/** The edit overlay: base data minus `removed`, plus `proposals`. */
type Edits = {
  removed: Fid[];
  proposals: Proposal[];
};

/** A replacement being set up in the type picker, previewed on the map. */
export type Draft = {
  fid: Fid;
  type: string;
  params: Record<string, number>;
};

type MapState = Edits & {
  selected: Fid | null;
  selectionStatus: SelectionStatus;
  /** Every base feature the user has selected, kept for outlines and footprints. */
  features: Record<Fid, BaseFeature>;
  /** Snapshots of the edits before each action, newest last. */
  history: Edits[];
  catalog: CatalogType[];
  draft: Draft | null;
  /** Analysis per proposal id, and the one the results panel shows. */
  analyses: Record<string, Analysis>;
  activeProposal: string | null;
  /** The persona picked from a map pin or card, highlighted in both. */
  focusedPersona: string | null;

  select: (feature: BaseFeature | null, status?: SelectionStatus) => void;
  /** Swap a pending selection for what it resolved to, if it is still selected. */
  resolve: (pendingFid: Fid, feature: BaseFeature, status: SelectionStatus) => void;
  remove: (fid: Fid) => void;
  setCatalog: (catalog: CatalogType[]) => void;
  startDraft: (fid: Fid) => void;
  setDraft: (patch: Partial<Omit<Draft, "fid">>) => void;
  cancelDraft: () => void;
  /** Commit the draft as a proposal; returns it so analysis can start. */
  commitDraft: () => Proposal | null;
  updateAnalysis: (proposalId: string, patch: Partial<Analysis>) => void;
  closePanel: () => void;
  focusPersona: (personaId: string | null) => void;
  undo: () => void;
};

const snapshot = ({ removed, proposals }: Edits): Edits => ({ removed, proposals });

export function defaultParams(t: CatalogType): Record<string, number> {
  return Object.fromEntries(Object.entries(t.params).map(([name, p]) => [name, p.default]));
}

export const useMapStore = create<MapState>()((set, get) => ({
  selected: null,
  selectionStatus: "ready",
  features: {},
  removed: [],
  proposals: [],
  history: [],
  catalog: [],
  draft: null,
  analyses: {},
  activeProposal: null,
  focusedPersona: null,

  select: (feature, status = "ready") =>
    set((s) =>
      feature
        ? {
            selected: feature.fid,
            selectionStatus: status,
            features: { ...s.features, [feature.fid]: feature },
            draft: null,
          }
        : { selected: null, draft: null },
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

  startDraft: (fid) =>
    set((s) => {
      const first = s.catalog[0];
      return first ? { draft: { fid, type: first.type, params: defaultParams(first) } } : {};
    }),

  setDraft: (patch) =>
    set((s) => {
      if (!s.draft) return {};
      // A new type starts from that type's defaults.
      const type = s.catalog.find((t) => t.type === (patch.type ?? s.draft?.type));
      const params =
        patch.type && patch.type !== s.draft.type && type ? defaultParams(type) : s.draft.params;
      return { draft: { ...s.draft, ...patch, params: { ...params, ...(patch.params ?? {}) } } };
    }),

  cancelDraft: () => set({ draft: null }),

  commitDraft: () => {
    const s = get();
    const feature = s.draft ? s.features[s.draft.fid] : null;
    if (!s.draft || !feature) return null;
    const proposal: Proposal = {
      id: crypto.randomUUID(),
      type: s.draft.type,
      params: s.draft.params,
      geometry: feature.footprint,
      replaces: [feature.fid],
    };
    set({
      history: [...s.history, snapshot(s)],
      removed: s.removed.includes(feature.fid) ? s.removed : [...s.removed, feature.fid],
      proposals: [...s.proposals, proposal],
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

  closePanel: () => set({ activeProposal: null, focusedPersona: null }),

  focusPersona: (focusedPersona) => set({ focusedPersona }),

  undo: () =>
    set((s) => {
      const previous = s.history.at(-1);
      if (!previous) return {};
      const keepPanel = previous.proposals.some((p) => p.id === s.activeProposal);
      return {
        ...previous,
        history: s.history.slice(0, -1),
        selected: null,
        draft: null,
        activeProposal: keepPanel ? s.activeProposal : null,
        focusedPersona: keepPanel ? s.focusedPersona : null,
      };
    }),
}));
