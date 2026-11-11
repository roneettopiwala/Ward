"use client";

import { MapPin, Minus, Pencil, Plus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { analyzeProposal } from "@/lib/analysis";
import { useMapStore } from "@/lib/store";
import { catalogMap, stackLabel, stackSummary } from "@/lib/parts";
import type { Analysis, Fact, PersonaCard, ProCon, Sentiment, Stance } from "@/lib/types";

import { km } from "./persona-pins";

const percent = (share: number) => `${Math.round(share * 100)}%`;

type Tab = "summary" | "personas" | "data";
/** Impact facts shown under a persona's reasons; the server lists the most important first. */
const IMPACT_SHOWN = 3;
type Filter = "all" | Stance;

const THEMES: Record<string, string> = {
  housing: "Housing",
  affordability: "Affordability",
  height_and_shadows: "Height & shadows",
  green_space: "Green space",
  transit: "Transit",
  traffic_and_parking: "Traffic & parking",
  construction: "Construction",
  noise_and_crowds: "Noise & crowds",
  local_business: "Local business",
  jobs: "Jobs",
  schools: "Schools",
  density: "Density",
  walkability: "Walkability",
  neighbourhood_character: "Neighbourhood character",
  events_and_tourism: "Events & tourism",
};

const STANCE: Record<Stance, { label: string; text: string; border: string; bg: string }> = {
  supports: { label: "Supports", text: "text-support", border: "border-support/60", bg: "bg-support" },
  neutral: { label: "Neutral", text: "text-neutral", border: "border-neutral/60", bg: "bg-neutral" },
  opposes: { label: "Opposes", text: "text-oppose", border: "border-oppose/60", bg: "bg-oppose" },
};

/** The header line: what the analysis is doing right now. */
function statusText(a: Analysis): string {
  if (a.status === "error") return "Analysis · Failed";
  if (a.status === "done") return "Analysis · Complete";
  if (a.status === "creating") return "Saving proposal";
  if (a.personaTotal) return `Analyzing · ${a.personas?.length ?? 0} of ${a.personaTotal} personas`;
  if (a.status === "personas") return "Meeting the neighbours · first visit";
  if (a.status === "writing") return "Writing pros and cons";
  return "Computing fact sheet";
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-fg-subtle">{children}</span>
  );
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

/** Shares by stance: the server's final numbers, or a live count while cards stream in. */
function shares(cards: PersonaCard[], sentiment: Sentiment | undefined) {
  if (sentiment) return sentiment;
  const n = cards.length || 1;
  const count = (s: Stance) => cards.filter((c) => c.stanceLabel === s).length / n;
  return { support: count("supports"), neutral: count("neutral"), oppose: count("opposes") };
}

/** "+6" / "−4" in percentage points against the previous version. */
function delta(now: number, before: number | undefined): string | null {
  if (before === undefined) return null;
  const d = Math.round(now * 100) - Math.round(before * 100);
  return d === 0 ? "±0" : d > 0 ? `+${d}` : `−${-d}`;
}

function SentimentBar({
  cards,
  sentiment,
  previous,
}: {
  cards: PersonaCard[];
  sentiment?: Sentiment;
  /** The previous version's sentiment, to show the change. */
  previous?: { version: number; sentiment: Sentiment };
}) {
  const s = shares(cards, sentiment);
  const before = sentiment && previous ? previous.sentiment : undefined;
  const parts = [
    { share: s.support, bg: "bg-support", label: "support", before: before?.support },
    { share: s.neutral, bg: "bg-neutral", label: "neutral", before: before?.neutral },
    { share: s.oppose, bg: "bg-oppose", label: "oppose", before: before?.oppose },
  ];
  return (
    <section className="mt-4" aria-label="Overall sentiment">
      <div className="flex items-baseline justify-between">
        <Label>Overall sentiment</Label>
        <span className="text-sm font-semibold">{sentiment ? sentiment.label : "Gathering reactions"}</span>
      </div>
      <div className="mt-2 flex h-1.5 gap-0.5 overflow-hidden rounded-full bg-surface-raised">
        {cards.length > 0 &&
          parts.map((p) => (
            <span
              key={p.label}
              className={`${p.bg} transition-[width] duration-500`}
              style={{ width: `${p.share * 100}%` }}
            />
          ))}
      </div>
      <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-fg-muted">
        {parts.map((p) => {
          const change = delta(p.share, p.before);
          return (
            <span key={p.label}>
              <span className="font-semibold text-fg">{percent(p.share)}</span> {p.label}
              {change && <span className="ml-1 font-mono text-fg-subtle">({change})</span>}
            </span>
          );
        })}
      </p>
      {before && previous && (
        <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.14em] text-fg-subtle">
          Change vs. V{previous.version}: {previous.sentiment.label} → {sentiment?.label}
        </p>
      )}
    </section>
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

function Themes({ sentiment }: { sentiment: Sentiment }) {
  if (!sentiment.themes.length) return null;
  return (
    <section className="mt-6">
      <Label>What people are talking about</Label>
      <ul className="mt-3 flex flex-col gap-2">
        {sentiment.themes.map((t) => (
          <li key={t.theme} className="flex items-center justify-between gap-3 text-sm">
            <span>{THEMES[t.theme] ?? t.theme}</span>
            <span className="flex gap-3 font-mono text-xs text-fg-muted">
              <span>{t.count} mention{t.count === 1 ? "" : "s"}</span>
              <span className="text-support">{t.support} for</span>
              <span className="text-oppose">{t.oppose} against</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2 font-mono text-[10px] uppercase tracking-[0.14em] text-fg-subtle">
        Source · Persona consensus
      </p>
    </section>
  );
}

function initials(name: string) {
  return name
    .split(/\s+/)
    .map((w) => w.charAt(0))
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function Card({ card, focused, onPin }: { card: PersonaCard; focused: boolean; onPin: () => void }) {
  const ref = useRef<HTMLLIElement>(null);
  const stance = STANCE[card.stanceLabel];
  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [focused]);

  return (
    <li
      ref={ref}
      className={`rounded-panel border p-4 ${focused ? "border-accent" : "border-border"} bg-surface`}
    >
      <div className="flex items-start gap-3">
        <span
          className={`flex size-9 shrink-0 items-center justify-center rounded-full border text-xs font-semibold ${stance.border}`}
          aria-hidden
        >
          {initials(card.persona.name)}
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">
            {card.persona.name}, {card.persona.age}
          </p>
          <p className="text-xs leading-snug text-fg-muted">{card.persona.tagline}</p>
        </div>
        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-xs ${stance.border} ${stance.text}`}>
          {stance.label}
        </span>
      </div>

      <blockquote className="mt-3 text-sm leading-relaxed">“{card.quote}”</blockquote>

      <div className="mt-3">
        <Label>What shapes this view</Label>
        <ul className="mt-2 flex list-disc flex-col gap-1 pl-4 text-xs leading-snug">
          {card.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
          {card.bullets.slice(0, IMPACT_SHOWN).map((b) => (
            <li key={b} className="text-fg-muted">
              {b}
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {card.themes.map((t) => (
          <span key={t} className="rounded-control border border-border px-2 py-0.5 text-xs text-fg-muted">
            {THEMES[t] ?? t}
          </span>
        ))}
      </div>

      <div className="mt-3 flex items-end justify-between gap-3">
        {card.persona.basedOn && (
          <p className="font-mono text-[10px] uppercase leading-relaxed tracking-[0.1em] text-fg-subtle">
            Based on · {card.persona.basedOn}
          </p>
        )}
        <button
          type="button"
          onClick={onPin}
          aria-label={`Show ${card.persona.name} on the map (${km(card.distanceM)} from the site)`}
          title={`${km(card.distanceM)} from the site`}
          className="shrink-0 rounded-control border border-border p-2 text-fg-muted hover:bg-surface-raised hover:text-fg"
        >
          <MapPin className="size-3.5" />
        </button>
      </div>
    </li>
  );
}

function Personas({ analysis, working }: { analysis: Analysis; working: boolean }) {
  const cards = analysis.personas ?? [];
  const focused = useMapStore((s) => s.focusedPersona);
  const focus = useMapStore((s) => s.focusPersona);
  const [filter, setFilter] = useState<Filter>("all");
  const count = (s: Stance) => cards.filter((c) => c.stanceLabel === s).length;
  // Most affected first: the people closest to the site.
  const shown = cards
    .filter((c) => filter === "all" || c.stanceLabel === filter)
    .toSorted((a, b) => a.distanceM - b.distanceM);
  const remaining = (analysis.personaTotal ?? 0) - cards.length;

  return (
    <div className="mt-4">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter personas">
        {(["all", "supports", "neutral", "opposes"] as const).map((f) => (
          <button
            key={f}
            type="button"
            aria-pressed={filter === f}
            onClick={() => setFilter(f)}
            className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs ${
              filter === f ? "border-fg bg-fg text-bg" : "border-border text-fg-muted hover:text-fg"
            }`}
          >
            {f !== "all" && <span className={`size-1.5 rounded-full ${STANCE[f].bg}`} />}
            {f === "all" ? `All ${cards.length}` : `${STANCE[f].label} ${count(f)}`}
          </button>
        ))}
      </div>
      <p className="mt-3 text-xs text-fg-subtle">Most affected first · fictional people sampled from census data</p>
      <ul className="mt-3 flex flex-col gap-3">
        {shown.map((c) => (
          <Card
            key={c.persona.id}
            card={c}
            focused={c.persona.id === focused}
            onPin={() => focus(c.persona.id)}
          />
        ))}
      </ul>
      {working && (
        <div className="mt-3" aria-hidden>
          {Array.from({ length: Math.min(remaining > 0 ? remaining : 3, 3) }, (_, i) => (
            <div key={i} className="mb-3 h-36 animate-pulse rounded-panel bg-surface-raised" />
          ))}
        </div>
      )}
    </div>
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

/** The results side panel for the open proposal: sentiment, pros and cons, personas and facts. */
export default function ResultsPanel() {
  const proposal = useMapStore((s) => s.proposals.find((p) => p.id === s.activeProposal));
  const analysis = useMapStore((s) => (s.activeProposal ? s.analyses[s.activeProposal] : undefined));
  const catalog = useMapStore((s) => s.catalog);
  const draft = useMapStore((s) => s.draft);
  const editProposal = useMapStore((s) => s.editProposal);
  const parentAnalysis = useMapStore((s) =>
    proposal?.parentId ? s.analyses[proposal.parentId] : undefined,
  );
  const focused = useMapStore((s) => s.focusedPersona);
  const closePanel = useMapStore((s) => s.closePanel);
  const [tab, setTab] = useState<Tab>("summary");

  // A pin clicked on the map opens its card.
  const [seenFocus, setSeenFocus] = useState(focused);
  if (focused !== seenFocus) {
    setSeenFocus(focused);
    if (focused) setTab("personas");
  }

  // The preview card takes this place while a change is being drafted.
  if (!proposal || !analysis || draft) return null;
  const types = catalogMap(catalog);
  const previous =
    parentAnalysis?.sentiment && proposal.version > 1
      ? { version: proposal.version - 1, sentiment: parentAnalysis.sentiment }
      : undefined;
  const { status, factSheet, pros, cons, personas = [], sentiment } = analysis;
  const facts = new Map(factSheet?.facts.map((f) => [f.id, f]));
  const working = status !== "done" && status !== "error";
  const tabLabel: Record<Tab, string> = {
    summary: "Summary",
    personas: analysis.personaTotal ? `Personas (${personas.length})` : "Personas",
    data: factSheet ? `Data (${factSheet.facts.length})` : "Data",
  };

  return (
    <aside
      aria-label="Proposal results"
      aria-busy={working}
      className="absolute bottom-4 right-4 top-4 z-20 flex w-[400px] max-w-[calc(100vw-32px)] flex-col rounded-panel border border-border bg-surface shadow-2xl shadow-black/40"
    >
      <header className="border-b border-border p-5 pb-4">
        <div className="flex items-center justify-between">
          <p
            className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle"
            aria-live="polite"
          >
            <span
              className={`size-2 rounded-full ${
                status === "error" ? "bg-oppose" : working ? "animate-pulse bg-accent" : "bg-accent"
              }`}
            />
            {statusText(analysis)}
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
        <div className="mt-3 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-lg font-semibold">
              {stackLabel(proposal.parts, types)}
              {proposal.version > 1 && (
                <span className="rounded border border-border-strong px-1.5 font-mono text-[10px] text-fg-muted">
                  V{proposal.version}
                </span>
              )}
            </h2>
            <p className="text-sm text-fg-muted">
              {[factSheet?.siteName, stackSummary(proposal.parts, types)].filter(Boolean).join(" · ")}
            </p>
          </div>
          <button
            type="button"
            disabled={working}
            onClick={() => editProposal(proposal.id)}
            title={working ? "Available when the analysis finishes" : "Adjust parts and parameters"}
            className="flex h-8 shrink-0 items-center gap-1.5 rounded-control border border-border-strong px-2.5 text-xs hover:bg-surface-raised disabled:opacity-40"
          >
            <Pencil className="size-3" /> Edit
          </button>
        </div>

        {(analysis.personaTotal || sentiment) && (
          <SentimentBar cards={personas} sentiment={sentiment} previous={previous} />
        )}

        <nav className="mt-4 flex gap-5 text-sm" aria-label="Result views">
          {(["summary", "personas", "data"] as const).map((t) => (
            <button
              key={t}
              type="button"
              aria-pressed={tab === t}
              onClick={() => setTab(t)}
              className={`-mb-4 border-b-2 pb-3 ${
                tab === t ? "border-accent text-fg" : "border-transparent text-fg-muted hover:text-fg"
              }`}
            >
              {tabLabel[t]}
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
            {sentiment && <Themes sentiment={sentiment} />}
            {personas.length > 0 && (
              <button
                type="button"
                onClick={() => setTab("personas")}
                className="mt-6 w-full rounded-control border border-border py-2 text-sm text-fg-muted hover:bg-surface-raised hover:text-fg"
              >
                See what {personas.length} people said
              </button>
            )}
          </>
        )}

        {tab === "personas" &&
          (analysis.personaTotal || personas.length ? (
            <Personas analysis={analysis} working={working} />
          ) : (
            working && (
              <p className="mt-5 text-sm text-fg-muted">
                {status === "personas"
                  ? "Meeting the people who live and work here. The first proposal in an area takes about a minute."
                  : "Choosing who reacts…"}
              </p>
            )
          ))}

        {tab === "data" && (factSheet ? <FactList facts={factSheet.facts} /> : working && <Skeleton rows={6} />)}
      </div>
    </aside>
  );
}
