"use client";

import bbox from "@turf/bbox";
import { ArrowRight, X } from "lucide-react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useState } from "react";

import { useMapStore } from "@/lib/store";
import type { BaseFeature } from "@/lib/types";

const CARD_WIDTH = 300;
const GAP = 16;
const EDGE = 16;

/** Screen position just east of the footprint, kept inside the viewport. */
function anchorFor(map: MapLibreMap, feature: BaseFeature): { left: number; top: number } {
  const [, s, e, n] = bbox(feature.footprint);
  const point = map.project([e, (s + n) / 2]);
  const { clientWidth, clientHeight } = map.getContainer();
  const fitsRight = point.x + GAP + CARD_WIDTH < clientWidth - EDGE;
  const left = fitsRight ? point.x + GAP : point.x - GAP - CARD_WIDTH;
  return {
    left: Math.min(Math.max(left, EDGE), clientWidth - CARD_WIDTH - EDGE),
    top: Math.min(Math.max(point.y - 110, 88), clientHeight - 300),
  };
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="font-mono text-[10px] uppercase tracking-[0.14em] text-fg-subtle">{label}</dt>
      <dd className="mt-0.5 text-sm">{value}</dd>
    </div>
  );
}

export default function SelectionCard({ map }: { map: MapLibreMap }) {
  const feature = useMapStore((s) => (s.selected ? s.features[s.selected] : null));
  const select = useMapStore((s) => s.select);
  const remove = useMapStore((s) => s.remove);
  const replace = useMapStore((s) => s.replace);
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

  return (
    <section
      aria-label="Selected building"
      style={{ left, top, width: CARD_WIDTH }}
      className="absolute z-10 rounded-panel border border-border bg-surface p-4 shadow-2xl shadow-black/40"
    >
      <header className="flex items-center justify-between">
        <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
          <span className="size-2 bg-accent" />
          Selected · Existing
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

      <h2 className="mt-3 text-lg font-semibold">{feature.name ?? "Unnamed building"}</h2>
      <p className="font-mono text-xs text-fg-subtle">{feature.fid}</p>

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3">
        <Field label="Use" value={feature.use ?? "—"} />
        <Field label="Height" value={feature.heightM ? `${feature.heightM} m` : "—"} />
        <Field label="Lot area" value="—" />
        <Field label="Zoning" value="—" />
      </dl>

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
          onClick={() => replace(feature.fid)}
          className="flex h-10 flex-1 items-center justify-center gap-2 rounded-control bg-accent text-sm font-semibold text-accent-fg hover:brightness-95"
        >
          Replace <ArrowRight className="size-4" />
        </button>
      </div>
    </section>
  );
}
