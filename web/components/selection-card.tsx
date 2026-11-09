"use client";

import bbox from "@turf/bbox";
import { ArrowRight, X } from "lucide-react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useState } from "react";

import { analyzeProposal } from "@/lib/analysis";
import { type Draft, useMapStore } from "@/lib/store";
import type { BaseFeature, CatalogType, SelectionStatus, TransitStop, Zoning } from "@/lib/types";

const CARD_WIDTH = 320;
const GAP = 16;
const EDGE = 16;

const NOTICES: Partial<Record<SelectionStatus, string>> = {
  "outside-area": "No city data for this area yet.",
  "not-found": "This building isn't in the city's building data.",
  error: "Couldn't load city data for this building.",
};

/** Screen position just east of the footprint, kept inside the viewport. */
function anchorFor(map: MapLibreMap, feature: BaseFeature): { left: number; top: number } {
  const [, s, e, n] = bbox(feature.footprint);
  const point = map.project([e, (s + n) / 2]);
  const { clientWidth, clientHeight } = map.getContainer();
  const fitsRight = point.x + GAP + CARD_WIDTH < clientWidth - EDGE;
  const left = fitsRight ? point.x + GAP : point.x - GAP - CARD_WIDTH;
  return {
    left: Math.min(Math.max(left, EDGE), clientWidth - CARD_WIDTH - EDGE),
    top: Math.min(Math.max(point.y - 110, 88), clientHeight - 480),
  };
}

const number = new Intl.NumberFormat("en-CA", { maximumFractionDigits: 0 });

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function zoningText(zoning: Zoning | null): string {
  if (!zoning) return "Not in By-law 569-2013";
  return zoning.maxHeightM ? `${zoning.code} · max ${zoning.maxHeightM} m` : zoning.code;
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-fg-subtle">
      {children}
    </span>
  );
}

function Field({ label, value, loading }: { label: string; value: string; loading: boolean }) {
  return (
    <div>
      <dt>
        <Label>{label}</Label>
      </dt>
      <dd className="mt-0.5 text-sm">
        {loading ? <span className="inline-block h-4 w-16 animate-pulse rounded bg-surface-raised" /> : value}
      </dd>
    </div>
  );
}

function Stops({ stops }: { stops: TransitStop[] }) {
  if (stops.length === 0) return null;
  return (
    <div className="mt-4">
      <Label>Nearest TTC</Label>
      <ul className="mt-1.5 flex flex-col gap-1.5">
        {stops.map((stop) => (
          <li key={stop.fid} className="text-sm">
            <p className="truncate" title={stop.name ?? undefined}>
              {stop.name}
            </p>
            <p className="flex justify-between font-mono text-[11px] text-fg-subtle">
              <span>
                {stop.mode} {stop.routes.join(", ")}
              </span>
              <span>{number.format(stop.distanceM)} m</span>
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

function formatParam(value: number, unit: string | null): string {
  return unit ? `${number.format(value)} ${unit}` : number.format(value);
}

/** Pick what replaces the building, with the type's main settings. Temporary until Phase 5. */
function TypePicker({ catalog, draft }: { catalog: CatalogType[]; draft: Draft }) {
  const setDraft = useMapStore((s) => s.setDraft);
  const cancelDraft = useMapStore((s) => s.cancelDraft);
  const commitDraft = useMapStore((s) => s.commitDraft);
  const type = catalog.find((t) => t.type === draft.type);
  const params = type ? Object.entries(type.params).filter(([, p]) => p.main) : [];

  return (
    <>
      <div className="mt-4">
        <Label>Replace with</Label>
        <div role="radiogroup" className="mt-2 flex flex-wrap gap-2">
          {catalog.map((t) => (
            <button
              key={t.type}
              type="button"
              role="radio"
              aria-checked={t.type === draft.type}
              onClick={() => setDraft({ type: t.type })}
              className={`h-9 rounded-control border px-3 text-sm ${
                t.type === draft.type
                  ? "border-accent bg-surface-raised text-fg"
                  : "border-border-strong text-fg-muted hover:bg-surface-raised"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-4">
        <Label>Parameters</Label>
        {params.length === 0 && (
          <p className="mt-1.5 text-sm text-fg-subtle">Nothing to set; it covers the whole site.</p>
        )}
        {params.map(([name, p]) => (
          <label key={name} className="mt-2 block">
            <span className="flex justify-between text-sm">
              {p.label}
              <span className="font-mono text-fg-muted">
                {formatParam(draft.params[name] ?? p.default, p.unit)}
              </span>
            </span>
            <input
              type="range"
              min={p.min}
              max={p.max}
              step={p.step}
              value={draft.params[name] ?? p.default}
              onChange={(e) => setDraft({ params: { [name]: Number(e.target.value) } })}
              className="mt-1 w-full accent-accent"
            />
          </label>
        ))}
      </div>

      <div className="mt-4 flex gap-2">
        <button
          type="button"
          onClick={cancelDraft}
          className="h-10 rounded-control border border-border-strong px-4 text-sm hover:bg-surface-raised"
        >
          Back
        </button>
        <button
          type="button"
          onClick={() => {
            const proposal = commitDraft();
            if (proposal) void analyzeProposal(proposal);
          }}
          className="flex h-10 flex-1 items-center justify-center gap-2 rounded-control bg-accent text-sm font-semibold text-accent-fg hover:brightness-95"
        >
          Analyze <ArrowRight className="size-4" />
        </button>
      </div>
    </>
  );
}

export default function SelectionCard({ map }: { map: MapLibreMap }) {
  const feature = useMapStore((s) => (s.selected ? s.features[s.selected] : null));
  const status = useMapStore((s) => s.selectionStatus);
  const select = useMapStore((s) => s.select);
  const remove = useMapStore((s) => s.remove);
  const catalog = useMapStore((s) => s.catalog);
  const draft = useMapStore((s) => s.draft);
  const startDraft = useMapStore((s) => s.startDraft);
  const [, rerender] = useState(0);

  useEffect(() => {
    const onMove = () => rerender((n) => n + 1);
    map.on("move", onMove);
    return () => {
      map.off("move", onMove);
    };
  }, [map]);

  if (!feature) return null;
  const { left, top } = anchorFor(map, feature);
  const loading = status === "loading";
  const details = feature.details;
  const notice = NOTICES[status];
  const picking = draft?.fid === feature.fid;

  return (
    <section
      aria-label="Selected building"
      aria-busy={loading}
      style={{ left, top, width: CARD_WIDTH }}
      className="absolute z-10 rounded-panel border border-border bg-surface p-4 shadow-2xl shadow-black/40"
    >
      <header className="flex items-center justify-between">
        <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
          <span className="size-2 bg-accent" />
          {picking ? "Replace · Draft" : "Selected · Existing"}
        </p>
        <button
          type="button"
          aria-label="Close"
          onClick={() => select(null)}
          className="rounded-control p-1 text-fg-muted hover:bg-surface-raised hover:text-fg"
        >
          <X className="size-4" />
        </button>
      </header>

      <h2 className="mt-3 text-lg font-semibold">
        {feature.name ?? (loading ? "Loading…" : "Unnamed building")}
      </h2>
      {details?.address && details.address !== feature.name && (
        <p className="text-sm text-fg-muted">{details.address}</p>
      )}
      {notice && <p className="mt-2 text-sm text-fg-subtle">{notice}</p>}

      {picking ? (
        <TypePicker catalog={catalog} draft={draft} />
      ) : (
        <>
          <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3">
            <Field label="Use" value={feature.use ? capitalize(feature.use) : "—"} loading={loading} />
            <Field
              label="Height"
              value={feature.heightM ? `${feature.heightM} m` : "—"}
              loading={loading}
            />
            <Field
              label="Lot area"
              value={details?.lotAreaM2 ? `${number.format(details.lotAreaM2)} m²` : "—"}
              loading={loading}
            />
            <Field label="Zoning" value={details ? zoningText(details.zoning) : "—"} loading={loading} />
          </dl>

          {details && <Stops stops={details.nearestStops} />}

          <div className="mt-4 flex gap-2">
            <button
              type="button"
              onClick={() => remove(feature.fid)}
              className="h-10 rounded-control border border-border-strong px-4 text-sm hover:bg-surface-raised"
            >
              Remove
            </button>
            <button
              type="button"
              disabled={catalog.length === 0 || loading}
              title={catalog.length === 0 ? "The type catalog hasn't loaded; is the API running?" : undefined}
              onClick={() => startDraft(feature.fid)}
              className="flex h-10 flex-1 items-center justify-center gap-2 rounded-control bg-accent text-sm font-semibold text-accent-fg hover:brightness-95 disabled:opacity-40"
            >
              Replace <ArrowRight className="size-4" />
            </button>
          </div>
        </>
      )}
    </section>
  );
}
