import { createProposal, streamAnalysis } from "./api";
import { useMapStore } from "./store";
import type { AnalysisStatus, Proposal } from "./types";

const STATUSES: Record<string, AnalysisStatus> = {
  analyzing: "analyzing",
  "writing pros and cons": "writing",
  done: "done",
};

/** Store the proposal on the API, then follow its analysis into the store. */
export async function analyzeProposal(proposal: Proposal): Promise<void> {
  const update = (patch: Parameters<ReturnType<typeof useMapStore.getState>["updateAnalysis"]>[1]) =>
    useMapStore.getState().updateAnalysis(proposal.id, patch);

  update({ status: "creating", error: undefined, factSheet: undefined, pros: undefined, cons: undefined });
  let serverId: string;
  try {
    serverId = await createProposal(proposal);
  } catch (e) {
    update({ status: "error", error: `Couldn't save the proposal: ${(e as Error).message}` });
    return;
  }
  update({ serverId, status: "analyzing" });
  streamAnalysis(serverId, {
    status: (s) => update({ status: STATUSES[s] ?? "analyzing" }),
    factSheet: (factSheet) => update({ factSheet }),
    prosCons: (pros, cons) => update({ pros, cons }),
    done: () => update({ status: "done" }),
    error: (error) => update({ status: "error", error }),
  });
}
