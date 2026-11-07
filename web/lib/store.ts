import { create } from "zustand";

import type { BaseFeature, Fid, Proposal } from "./types";

/** The edit overlay: base data minus `removed`, plus `proposals`. */
type Edits = {
  removed: Fid[];
  proposals: Proposal[];
};

type MapState = Edits & {
  selected: Fid | null;
  /** Every base feature the user has selected, kept for outlines and footprints. */
  features: Record<Fid, BaseFeature>;
  /** Snapshots of the edits before each action, newest last. */
  history: Edits[];
  select: (feature: BaseFeature | null) => void;
  remove: (fid: Fid) => void;
  replace: (fid: Fid) => void;
  undo: () => void;
};

const snapshot = ({ removed, proposals }: Edits): Edits => ({ removed, proposals });

export const useMapStore = create<MapState>()((set) => ({
  selected: null,
  features: {},
  removed: [],
  proposals: [],
  history: [],

  select: (feature) =>
    set((s) =>
      feature
        ? { selected: feature.fid, features: { ...s.features, [feature.fid]: feature } }
        : { selected: null },
    ),

  remove: (fid) =>
    set((s) => {
      if (s.removed.includes(fid)) return {};
      return {
        history: [...s.history, snapshot(s)],
        removed: [...s.removed, fid],
        selected: null,
      };
    }),

  replace: (fid) =>
    set((s) => {
      const feature = s.features[fid];
      if (!feature) return {};
      const proposal: Proposal = {
        id: crypto.randomUUID(),
        type: "placeholder",
        params: {},
        geometry: feature.footprint,
        replaces: [fid],
      };
      return {
        history: [...s.history, snapshot(s)],
        removed: s.removed.includes(fid) ? s.removed : [...s.removed, fid],
        proposals: [...s.proposals, proposal],
        selected: null,
      };
    }),

  undo: () =>
    set((s) => {
      const previous = s.history.at(-1);
      if (!previous) return {};
      return { ...previous, history: s.history.slice(0, -1), selected: null };
    }),
}));
