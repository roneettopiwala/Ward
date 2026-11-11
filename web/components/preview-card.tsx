"use client";

import { ArrowRight, Plus, X } from "lucide-react";
import { useState } from "react";

import { analyzeProposal } from "@/lib/analysis";
import { catalogMap, homesOf, partLabel, stackHeight, stackLabel } from "@/lib/parts";
import { useMapStore } from "@/lib/store";
import type { CatalogParam, CatalogType, Part } from "@/lib/types";

import { PROMPT_INPUT_ID } from "./prompt-bar";

const number = new Intl.NumberFormat("en-CA", { maximumFractionDigits: 0 });

function Label({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-fg-subtle">{children}</span>
  );
}

/** One slider. Heights move in whole storeys and show both storeys and metres. */
function ParamSlider({
  name,
  param,
  type,
  value,
  onChange,
}: {
  name: string;
  param: CatalogParam;
  type: CatalogType;
  value: number;
  onChange: (value: number) => void;
}) {
  const storeyM = name === type.render.heightParam ? type.storeyM : null;
  if (storeyM) {
    const min = Math.max(1, Math.ceil(param.min / storeyM));
    const max = Math.floor(param.max / storeyM);
    const storeys = Math.min(max, Math.max(min, Math.round(value / storeyM)));
    return (
      <label className="mt-3 block">
        <span className="flex justify-between text-sm">
          {param.label}
          <span className="font-mono text-fg-muted">
            {storeys} storey{storeys === 1 ? "" : "s"} · {number.format(value)} m
          </span>
        </span>
        <input
          type="range"
          min={min}
          max={max}
          step={1}
          value={storeys}
          aria-valuetext={`${storeys} storeys, ${number.format(value)} metres`}
          onChange={(e) => onChange(Math.round(Number(e.target.value) * storeyM * 10) / 10)}
          className="mt-1 w-full accent-accent"
        />
      </label>
    );
  }
  return (
    <label className="mt-3 block">
      <span className="flex justify-between text-sm">
        {param.label}
        <span className="font-mono text-fg-muted">
          {number.format(value)} {param.unit ?? ""}
        </span>
      </span>
      <input
        type="range"
        min={param.min}
        max={param.max}
        step={param.step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-1 w-full accent-accent"
      />
    </label>
  );
}

function PartChip({ parts, index, catalog }: { parts: Part[]; index: number; catalog: CatalogType[] }) {
  const setPartType = useMapStore((s) => s.setPartType);
  const removePart = useMapStore((s) => s.removePart);
  const part = parts[index];
  const types = catalogMap(catalog);
  return (
    <li className="flex items-center gap-1 rounded-control border border-border-strong bg-surface-raised pl-2">
      <select
        aria-label={`Type of part ${index + 1}`}
        value={part.type}
        onChange={(e) => setPartType(index, e.target.value)}
        className="h-8 bg-transparent text-sm focus:outline-none"
      >
        {catalog.map((t) => (
          <option key={t.type} value={t.type} className="bg-surface">
            {t.type === part.type ? partLabel(parts, index, types) : t.label}
          </option>
        ))}
      </select>
      {part.tags.length > 0 && <span className="text-xs text-fg-muted">· {part.tags.join(", ")}</span>}
      {parts.length > 1 ? (
        <button
          type="button"
          aria-label={`Remove ${partLabel(parts, index, types)}`}
          onClick={() => removePart(index)}
          className="p-1.5 text-fg-subtle hover:text-fg"
        >
          <X className="size-3.5" />
        </button>
      ) : (
        <span className="w-2" />
      )}
    </li>
  );
}

/** The preview card: what the prompt was read as, editable before analysis. */
export default function PreviewCard() {
  const draft = useMapStore((s) => s.draft);
  const catalog = useMapStore((s) => s.catalog);
  const feature = useMapStore((s) => (s.draft ? s.features[s.draft.fid] : undefined));
  const parent = useMapStore((s) => s.proposals.find((p) => p.id === s.draft?.parentId));
  const setDraft = useMapStore((s) => s.setDraft);
  const setPartParam = useMapStore((s) => s.setPartParam);
  const addPart = useMapStore((s) => s.addPart);
  const commitDraft = useMapStore((s) => s.commitDraft);
  const setPromptText = useMapStore((s) => s.setPromptText);
  const [adding, setAdding] = useState(false);

  if (!draft || !feature) return null;
  const types = catalogMap(catalog);
  const { heightM, storeys } = stackHeight(draft.parts, types);
  const homes = homesOf(draft.parts);
  const siteName = feature.name ?? "Selected site";

  const analyze = () => {
    const proposal = commitDraft();
    if (proposal) void analyzeProposal(proposal);
  };

  return (
    <aside
      aria-label="Proposal preview"
      className="absolute bottom-4 right-4 top-4 z-20 flex w-[400px] max-w-[calc(100vw-32px)] flex-col rounded-panel border border-border bg-surface shadow-2xl shadow-black/40"
    >
      <header className="border-b border-border p-5 pb-4">
        <div className="flex items-center justify-between">
          <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
            <span className="size-2 bg-accent" />
            Preview · {parent ? `V${parent.version + 1} draft` : "Draft"}
          </p>
          {draft.prompt && (
            <button
              type="button"
              onClick={() => {
                setPromptText(draft.prompt ?? "");
                document.getElementById(PROMPT_INPUT_ID)?.focus();
              }}
              className="h-8 rounded-control border border-border-strong px-2.5 text-xs hover:bg-surface-raised"
            >
              Edit prompt
            </button>
          )}
        </div>
        {draft.prompt ? (
          <p className="mt-3 text-lg font-semibold leading-snug">“{draft.prompt}”</p>
        ) : (
          <p className="mt-3 text-lg font-semibold">Editing V{parent?.version ?? 1}</p>
        )}
        <p className="mt-1 text-sm text-fg-muted">
          {siteName}
          {feature.details?.address && feature.details.address !== feature.name
            ? ` · ${feature.details.address}`
            : ""}
        </p>
      </header>

      <div className="flex-1 overflow-y-auto p-5">
        <Label>Interpreted as · {stackLabel(draft.parts, types)}</Label>
        <ul className="mt-2 flex flex-wrap items-center gap-2" aria-label="Parts, bottom to top">
          {draft.parts.map((_, i) => (
            <PartChip key={i} parts={draft.parts} index={i} catalog={catalog} />
          ))}
          <li>
            <button
              type="button"
              aria-expanded={adding}
              aria-label="Add a part"
              onClick={() => setAdding((a) => !a)}
              className="flex size-8 items-center justify-center rounded-control border border-dashed border-border-strong text-fg-muted hover:text-fg"
            >
              <Plus className="size-3.5" />
            </button>
          </li>
        </ul>
        {adding && (
          <div className="mt-2 flex flex-wrap gap-2">
            {catalog.map((t) => (
              <button
                key={t.type}
                type="button"
                onClick={() => {
                  addPart(t.type);
                  setAdding(false);
                }}
                className="h-8 rounded-control border border-border px-3 text-xs text-fg-muted hover:text-fg"
              >
                + {t.render.kind === "flat" && draft.parts.length > 0 ? `Rooftop ${t.label.toLowerCase()}` : t.label}
              </button>
            ))}
          </div>
        )}

        <div className="mt-5">
          <Label>Parameters</Label>
          {draft.parts.map((part, i) => {
            const t = types.get(part.type);
            const params = Object.entries(t?.params ?? {});
            if (!t || params.length === 0) return null;
            return (
              <div key={i} className="mt-2">
                {draft.parts.length > 1 && (
                  <p className="mt-3 text-xs font-semibold text-fg-muted">{partLabel(draft.parts, i, types)}</p>
                )}
                {params.map(([name, p]) => (
                  <ParamSlider
                    key={name}
                    name={name}
                    param={p}
                    type={t}
                    value={part.params[name] ?? p.default}
                    onChange={(v) => setPartParam(i, name, v)}
                  />
                ))}
              </div>
            );
          })}
          {draft.parts.length > 1 && heightM > 0 && (
            <p className="mt-3 font-mono text-xs text-fg-muted">
              Total · {storeys} storeys · {number.format(heightM)} m
              {homes ? ` · ${number.format(homes)} homes` : ""}
            </p>
          )}
        </div>

        {(draft.assumptions.length > 0 || !draft.replacesExisting) && (
          <div className="mt-5">
            <Label>Assumptions</Label>
            <ul className="mt-2 flex list-disc flex-col gap-1 pl-4 text-xs leading-snug text-fg-muted">
              {!draft.replacesExisting && (
                <li className="text-fg">
                  Ward can&apos;t build beside an existing building yet, so this preview replaces {siteName}.
                </li>
              )}
              {draft.assumptions.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <footer className="border-t border-border p-5">
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setDraft(null)}
            className="h-10 rounded-control border border-border-strong px-4 text-sm hover:bg-surface-raised"
          >
            Discard
          </button>
          <button
            type="button"
            onClick={analyze}
            className="flex h-10 flex-1 items-center justify-center gap-2 rounded-control bg-accent text-sm font-semibold text-accent-fg hover:brightness-95"
          >
            Analyze <ArrowRight className="size-4" />
          </button>
        </div>
        <p className="mt-3 text-xs text-fg-subtle">
          Runs against about 15 personas drawn from 2021 Census profiles for the area.
        </p>
      </footer>
    </aside>
  );
}
