"use client";

import { Minus, Plus, X } from "lucide-react";
import { useState } from "react";

import { analyzeProposal } from "@/lib/analysis";
import { useMapStore } from "@/lib/store";
import type { Analysis, CatalogType, Fact, ProCon, Proposal } from "@/lib/types";

const STATUS_TEXT: Record<Analysis["status"], string> = {
  creating: "Saving proposal",
  analyzing: "Computing fact sheet",
  writing: "Writing pros and cons",
  done: "Analysis · Complete",
  error: "Analysis · Failed",
};

const number = new Intl.NumberFormat("en-CA", { maximumFractionDigits: 0 });

function Label({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-fg-subtle">
      {children}
    </span>
  );
}

/** "Rogers Centre · 20 m" from the site and the type's main params. */
function subtitle(proposal: Proposal, type: CatalogType | undefined, site: string | undefined) {
  const params = Object.entries(type?.params ?? {})
    .filter(([, p]) => p.main)
    .map(([name, p]) => `${number.format(proposal.params[name] ?? p.default)} ${p.unit ?? ""}`.trim());
  return [site, ...params].filter(Boolean).join(" · ");
}

function Skeleton({ rows }: { rows: number }) {
  return (
    <ul className="mt-3 flex flex-col gap-3" aria-hidden>
      {Array.from({ length: rows }, (_, i) => (
        <li key={i} className="flex gap-3">
          <span className="size-5 shrink-0 animate-pulse rounded bg-surface-raised" />
          <span className="h-9 flex-1 animate-pulse rounded bg-surface-raised" />
        </li>
      ))}
    </ul>
  );
}

function Points({ kind, points, facts }: { kind: "pro" | "con"; points: ProCon[]; facts: Map<string, Fact> }) {
  const Icon = kind === "pro" ? Plus : Minus;
  return (
    <section className="mt-5">
      <Label>
        {kind === "pro" ? "Pros" : "Cons"} · {points.length}
      </Label>
      <ul className="mt-3 flex flex-col gap-4">
        {points.map((p) => (
          <li
            key={p.text}
            className="flex gap-3"
            // Hover shows the exact facts behind the claim.
            title={p.facts.map((id) => facts.get(id)).filter(Boolean).map((f) => `${f!.label}: ${f!.display}`).join("\n")}
          >
            <span
              className={`flex size-5 shrink-0 items-center justify-center rounded border ${
                kind === "pro" ? "border-accent/40 text-accent" : "border-oppose/40 text-oppose"
              }`}
            >
              <Icon className="size-3" strokeWidth={2.5} />
            </span>
            <div>
              <p className="text-sm leading-snug">{p.text}</p>
              <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.14em] text-fg-subtle">
                Source · {p.sources.join(" · ")}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function FactList({ facts }: { facts: Fact[] }) {
  return (
    <dl className="mt-4 flex flex-col divide-y divide-border">
      {facts.map((f) => (
        <div key={f.id} className="flex justify-between gap-4 py-2 text-sm">
          <dt className="text-fg-muted">{f.label}</dt>
          <dd className="text-right">{f.display}</dd>
        </div>
      ))}
    </dl>
  );
}

/** The results side panel for the open proposal: status, pros and cons, and its facts. */
export default function ResultsPanel() {
  const proposal = useMapStore((s) => s.proposals.find((p) => p.id === s.activeProposal));
  const analysis = useMapStore((s) => (s.activeProposal ? s.analyses[s.activeProposal] : undefined));
  const type = useMapStore((s) => s.catalog.find((t) => t.type === proposal?.type));
  const closePanel = useMapStore((s) => s.closePanel);
  const [tab, setTab] = useState<"summary" | "data">("summary");

  if (!proposal || !analysis) return null;
  const { status, factSheet, pros, cons } = analysis;
  const facts = new Map(factSheet?.facts.map((f) => [f.id, f]));
  const working = status !== "done" && status !== "error";

  return (
    <aside
      aria-label="Proposal results"
      aria-busy={working}
      className="absolute bottom-4 right-4 top-4 z-20 flex w-[400px] max-w-[calc(100vw-32px)] flex-col rounded-panel border border-border bg-surface shadow-2xl shadow-black/40"
    >
      <header className="border-b border-border p-5 pb-4">
        <div className="flex items-center justify-between">
          <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
            <span
              className={`size-2 rounded-full ${
                status === "error" ? "bg-oppose" : working ? "animate-pulse bg-accent" : "bg-accent"
              }`}
            />
            {STATUS_TEXT[status]}
          </p>
          <button
            type="button"
            aria-label="Close results"
            onClick={closePanel}
            className="rounded-control p-1 text-fg-muted hover:bg-surface-raised hover:text-fg"
          >
            <X className="size-4" />
          </button>
        </div>
        <h2 className="mt-3 text-lg font-semibold">{type?.label ?? proposal.type}</h2>
        <p className="text-sm text-fg-muted">{subtitle(proposal, type, factSheet?.siteName)}</p>

        <nav className="mt-4 flex gap-5 text-sm" aria-label="Result views">
          {(["summary", "data"] as const).map((t) => (
            <button
              key={t}
              type="button"
              aria-pressed={tab === t}
              onClick={() => setTab(t)}
              className={`-mb-4 border-b-2 pb-3 capitalize ${
                tab === t ? "border-accent text-fg" : "border-transparent text-fg-muted hover:text-fg"
              }`}
            >
              {t === "data" && factSheet ? `Data (${factSheet.facts.length})` : t}
            </button>
          ))}
        </nav>
      </header>

      <div className="flex-1 overflow-y-auto p-5 pt-0">
        {status === "error" && (
          <div className="mt-5 rounded-control border border-oppose/40 p-3 text-sm">
            <p>{analysis.error}</p>
            <button
              type="button"
              onClick={() => void analyzeProposal(proposal)}
              className="mt-3 h-9 rounded-control border border-border-strong px-3 hover:bg-surface-raised"
            >
              Try again
            </button>
          </div>
        )}

        {tab === "summary" && (
          <>
            {pros && cons ? (
              <>
                <Points kind="pro" points={pros} facts={facts} />
                <Points kind="con" points={cons} facts={facts} />
              </>
            ) : (
              working && (
                <div className="mt-5">
                  <Label>{factSheet ? `Writing from ${factSheet.facts.length} facts` : "Pros and cons"}</Label>
                  <Skeleton rows={3} />
                  <div className="mt-5">
                    <Label>Cons</Label>
                  </div>
                  <Skeleton rows={3} />
                </div>
              )
            )}
          </>
        )}

        {tab === "data" &&
          (factSheet ? (
            <FactList facts={factSheet.facts} />
          ) : (
            working && <Skeleton rows={6} />
          ))}
      </div>
    </aside>
  );
}
