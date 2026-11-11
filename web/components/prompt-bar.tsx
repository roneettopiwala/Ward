"use client";

import { ArrowRight, Loader2, MessageCircleQuestion } from "lucide-react";
import { useState } from "react";

import { parsePrompt } from "@/lib/api";
import { useMapStore } from "@/lib/store";
import type { Part } from "@/lib/types";

import { zoningText } from "./selection-card";

export const PROMPT_INPUT_ID = "prompt-input";

const SUGGESTIONS = [
  { label: "Mixed-use with a park", prompt: "Shops on the ground floor, homes above and a rooftop park" },
  { label: "Affordable housing", prompt: "A 30 storey affordable housing tower" },
  { label: "Food hall", prompt: "A mall with a food hall and a rooftop park" },
  { label: "Public park", prompt: "Turn it into a public park" },
];

type Mode = "describe" | "update" | "refine";

const MODES: Record<Mode, { placeholder: string; button: string }> = {
  describe: { placeholder: "Describe what you want to build here…", button: "Preview" },
  update: { placeholder: "Change the preview, e.g. “add a rooftop park”…", button: "Update" },
  refine: { placeholder: "Ask a follow-up or change the proposal…", button: "Refine" },
};

/**
 * The prompt bar: describe what to build on the selection (Preview), change a
 * preview in words (Update), or change an analyzed proposal (Refine). Every
 * path opens the preview card; nothing is analyzed until Analyze is pressed.
 */
export default function PromptBar() {
  const draft = useMapStore((s) => s.draft);
  const selected = useMapStore((s) => s.selected);
  const selectionStatus = useMapStore((s) => s.selectionStatus);
  const active = useMapStore((s) => s.proposals.find((p) => p.id === s.activeProposal));
  const features = useMapStore((s) => s.features);
  const text = useMapStore((s) => s.promptText);
  const setText = useMapStore((s) => s.setPromptText);
  const setDraft = useMapStore((s) => s.setDraft);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clarify, setClarify] = useState<{ question: string; prompt: string } | null>(null);

  // What the bar acts on: an open preview, else a fresh selection, else the open results.
  const mode: Mode | null = draft ? "update" : selected ? "describe" : active ? "refine" : null;
  const fid = draft?.fid ?? selected ?? active?.replaces[0];
  const feature = fid ? features[fid] : undefined;
  if (!mode || !fid || !feature || (mode === "describe" && selectionStatus === "loading")) return null;

  const current: Part[] | undefined =
    mode === "update" ? draft?.parts : mode === "refine" ? active?.parts : undefined;
  const parentId = mode === "update" ? (draft?.parentId ?? null) : mode === "refine" ? active!.id : null;
  const sidePanelOpen = Boolean(draft || active);

  async function submit() {
    const typed = text.trim();
    if (!typed || busy || !fid || !feature) return;
    // An answer to a clarifying question is read together with the original request.
    const prompt = clarify ? `${clarify.prompt}. ${typed}` : typed;
    setBusy(true);
    setError(null);
    try {
      const result = await parsePrompt({
        prompt,
        geometryType: feature.footprint.type,
        selection: {
          name: feature.name,
          use: feature.use,
          heightM: feature.heightM,
          lotAreaM2: feature.details?.lotAreaM2 ?? null,
          zoning: feature.details ? zoningText(feature.details.zoning) : null,
        },
        current,
      });
      if (result.clarification) {
        setClarify({ question: result.clarification, prompt });
      } else {
        setClarify(null);
        setDraft({
          fid,
          parts: result.parts,
          prompt,
          assumptions: result.assumptions,
          replacesExisting: result.replacesExisting,
          parentId,
        });
      }
      setText("");
    } catch (e) {
      setError((e as Error).message || "Couldn't reach the API.");
    } finally {
      setBusy(false);
    }
  }

  const { placeholder, button } = MODES[mode];

  return (
    <div
      className={`absolute bottom-6 z-20 flex flex-col gap-2 ${
        sidePanelOpen
          ? "left-4 right-[432px] mx-auto max-w-[640px]"
          : "left-1/2 w-[min(640px,calc(100vw-32px))] -translate-x-1/2"
      }`}
    >
      {mode === "describe" && !clarify && (
        <div className="flex flex-wrap justify-center gap-2" role="group" aria-label="Suggestions">
          {SUGGESTIONS.map((s) => (
            <button
              key={s.label}
              type="button"
              onClick={() => setText(s.prompt)}
              className="h-8 rounded-full border border-border bg-surface/90 px-3 text-xs text-fg-muted backdrop-blur hover:text-fg"
            >
              {s.label}
            </button>
          ))}
        </div>
      )}

      {clarify && (
        <p
          role="status"
          className="flex items-start gap-2 rounded-control border border-accent/40 bg-surface px-3 py-2 text-sm"
        >
          <MessageCircleQuestion className="mt-0.5 size-4 shrink-0 text-accent" />
          <span className="flex-1">{clarify.question}</span>
          <button
            type="button"
            onClick={() => setClarify(null)}
            className="text-xs text-fg-subtle hover:text-fg"
          >
            Start over
          </button>
        </p>
      )}
      {error && (
        <p role="alert" className="rounded-control border border-oppose/40 bg-surface px-3 py-2 text-sm">
          {error}
        </p>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        className="flex items-center gap-3 rounded-panel border border-border-strong bg-surface p-2 pl-4 shadow-2xl shadow-black/40"
      >
        <label
          htmlFor={PROMPT_INPUT_ID}
          className="max-w-[30%] shrink-0 truncate font-mono text-[11px] uppercase tracking-[0.14em] text-accent"
        >
          {feature.name ?? "Selected site"} ›
        </label>
        <input
          id={PROMPT_INPUT_ID}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={clarify ? "Your answer…" : placeholder}
          maxLength={500}
          autoComplete="off"
          disabled={busy}
          className="h-10 min-w-0 flex-1 bg-transparent text-sm placeholder:text-fg-subtle focus:outline-none disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={busy || !text.trim()}
          className="flex h-10 shrink-0 items-center gap-2 rounded-control bg-accent px-4 text-sm font-semibold text-accent-fg hover:brightness-95 disabled:opacity-40"
        >
          {busy ? <Loader2 className="size-4 animate-spin" /> : null}
          {busy ? "Reading" : clarify ? "Answer" : button}
          {!busy && <ArrowRight className="size-4" />}
        </button>
      </form>
    </div>
  );
}
