"use client";

import bbox from "@turf/bbox";
import { ArrowDown, X } from "lucide-react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useState } from "react";

import { selectFeature } from "@/lib/selection";
import { useMapStore } from "@/lib/store";
import {
  type BaseFeature,
  type FeatureKind,
  REPLACEABLE,
  type SelectionStatus,
  type TransitStop,
  type Zoning,
} from "@/lib/types";

const CARD_WIDTH = 320;
const GAP = 16;
const EDGE = 16;

const NOTICES: Partial<Record<SelectionStatus, string>> = {
  "not-found": "This isn't in Ward's city data yet.",
  error: "Couldn't load city data for this.",
};

const KIND_LABEL: Record<FeatureKind, string> = {
  building: "Building",
  parcel: "Lot",
  park: "Park",
  transit: "Transit stop",
  cycling: "Cycling route",
  street: "Street",
  drawn: "Drawn area",
};

function kindLabel(feature: BaseFeature): string {
  if (feature.kind !== "drawn") return KIND_LABEL[feature.kind];
  const t = feature.geometry.type;
  return t === "LineString" || t === "MultiLineString" ? "Drawn line" : t === "Point" ? "Drawn point" : "Drawn area";
}

const FACILITY: Record<string, string> = {
  painted: "Painted bike lane",
  protected: "Protected cycle track",
  trail: "Multi-use trail",
  shared: "Shared lane (sharrows)",
};

/** Screen position just east of the feature, kept inside the viewport. */
function anchorFor(map: MapLibreMap, feature: BaseFeature): { left: number; top: number } {
  const [, s, e, n] = bbox(feature.geometry);
  const point = map.project([e, (s + n) / 2]);
  const { clientWidth, clientHeight } = map.getContainer();
  const fitsRight = point.x + GAP + CARD_WIDTH < clientWidth - EDGE;
  const left = fitsRight ? point.x + GAP : point.x - GAP - CARD_WIDTH;
  return {
    left: Math.min(Math.max(left, EDGE), clientWidth - CARD_WIDTH - EDGE),
    // Clear of the prompt bar at the bottom (up to about 200 px with a question showing).
    top: Math.min(Math.max(point.y - 110, 88), clientHeight - 660),
  };
}

const number = new Intl.NumberFormat("en-CA", { maximumFractionDigits: 0 });

function capitalize(value: string): string {
  const words = value.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const metres = (m: number | null | undefined) =>
  m ? (m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${number.format(m)} m`) : "—";
const area = (m2: number | null | undefined) =>
  m2 ? (m2 >= 10_000 ? `${(m2 / 10_000).toFixed(1)} ha` : `${number.format(m2)} m²`) : "—";

/** The facts shown for each kind of feature. */
function fieldsFor(feature: BaseFeature): [string, string][] {
  const d = feature.details;
  const zoning: [string, string] = ["Zoning", d ? zoningText(d.zoning) : "—"];
  switch (feature.kind) {
    case "building":
      return [
        ["Use", feature.use ? capitalize(feature.use) : "—"],
        ["Height", feature.heightM ? `${feature.heightM} m` : "—"],
        ["Lot area", area(d?.lotAreaM2)],
        zoning,
      ];
    case "parcel":
    case "park":
      return [[feature.kind === "park" ? "Area" : "Lot area", area(d?.lotAreaM2)], zoning];
    case "transit":
      return [
        ["Mode", d?.mode ? capitalize(d.mode) : "—"],
        ["Routes", d?.routes.length ? d.routes.join(", ") : "—"],
      ];
    case "cycling":
      return [
        ["Facility", d?.facilityType ? (FACILITY[d.facilityType] ?? d.facilityType) : "—"],
        ["Installed", d?.installed ? String(d.installed) : "—"],
        ["Segment length", metres(d?.lengthM)],
      ];
    case "street":
      return [
        ["Road class", d?.roadClass ? capitalize(d.roadClass) : "—"],
        ["Segment length", metres(d?.lengthM)],
      ];
    case "drawn": {
      const site = feature.drawn;
      const removes = site?.replaces.length ?? 0;
      const size: [string, string][] = site?.lengthM
        ? [["Length", metres(site.lengthM)]]
        : site?.areaM2
          ? [["Area", area(site.areaM2)]]
          : [];
      return [
        ...size,
        ["Removes", removes ? `${removes} building${removes === 1 ? "" : "s"}` : "Nothing"],
        ...(site?.streets.length
          ? ([["Follows", site.streets.slice(0, 3).join(", ")]] as [string, string][])
          : []),
      ];
    }
  }
}

export function zoningText(zoning: Zoning | null): string {
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

export default function SelectionCard({ map }: { map: MapLibreMap }) {
  const feature = useMapStore((s) => (s.selected ? s.features[s.selected] : null));
  const status = useMapStore((s) => s.selectionStatus);
  const alsoHere = useMapStore((s) => s.alsoHere);
  const select = useMapStore((s) => s.select);
  const remove = useMapStore((s) => s.remove);
  const draft = useMapStore((s) => s.draft);
  const [, rerender] = useState(0);

  useEffect(() => {
    const onMove = () => rerender((n) => n + 1);
    map.on("move", onMove);
    return () => {
      map.off("move", onMove);
    };
  }, [map]);

  // While a preview is open, the preview card takes over.
  if (!feature || draft) return null;
  const { left, top } = anchorFor(map, feature);
  const loading = status === "loading";
  const details = feature.details;
  const notice = NOTICES[status];
  const replaceable = REPLACEABLE.includes(feature.kind);
  const label = kindLabel(feature);
  const subtitle = details?.address && details.address !== feature.name ? details.address : null;

  return (
    <section
      aria-label={`Selected ${label.toLowerCase()}`}
      aria-busy={loading}
      style={{ left, top, width: CARD_WIDTH }}
      className="absolute z-10 rounded-panel border border-border bg-surface p-4 shadow-2xl shadow-black/40"
    >
      <header className="flex items-center justify-between">
        <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
          <span className="size-2 bg-accent" />
          Selected · {label}
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
        {feature.name ?? (loading ? "Loading…" : `Unnamed ${label.toLowerCase()}`)}
      </h2>
      {subtitle && <p className="text-sm text-fg-muted">{subtitle}</p>}
      {notice && <p className="mt-2 text-sm text-fg-subtle">{notice}</p>}
      {feature.drawn?.warnings.map((w) => (
        <p key={w} className="mt-2 text-sm text-fg-muted">
          {w}
        </p>
      ))}

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3">
        {fieldsFor(feature).map(([label, value]) => (
          <Field key={label} label={label} value={value} loading={loading} />
        ))}
      </dl>

      {details && <Stops stops={details.nearestStops} />}

      {alsoHere.length > 0 && (
        <div className="mt-4">
          <Label>Also here</Label>
          <ul className="mt-1.5 flex flex-wrap gap-1.5">
            {alsoHere.map((other) => (
              <li key={other.fid}>
                <button
                  type="button"
                  onClick={() =>
                    void selectFeature(other, [feature, ...alsoHere.filter((a) => a.fid !== other.fid)])
                  }
                  className="max-w-[280px] truncate rounded-control border border-border px-2 py-1 text-left text-xs text-fg-muted hover:text-fg"
                >
                  {KIND_LABEL[other.kind]}
                  {other.name ? ` · ${other.name}` : ""}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {replaceable ? (
        <div className="mt-4 flex items-center justify-between gap-2">
          <p className="flex items-center gap-1.5 text-xs text-fg-subtle">
            <ArrowDown className="size-3.5" /> Describe what to build in the bar below
          </p>
          <button
            type="button"
            onClick={() => (feature.kind === "drawn" ? select(null) : remove(feature.fid))}
            className="h-9 shrink-0 rounded-control border border-border-strong px-3 text-sm hover:bg-surface-raised"
          >
            {feature.kind === "drawn" ? "Discard" : "Remove"}
          </button>
        </div>
      ) : (
        <p className="mt-4 text-xs text-fg-subtle">Shown for information. Proposals replace buildings, lots and parks.</p>
      )}
    </section>
  );
}
