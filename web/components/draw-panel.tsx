"use client";

import area from "@turf/area";
import length from "@turf/length";
import { Loader2 } from "lucide-react";

import type { DrawController } from "@/lib/draw";
import { type AreaTool, type Tool, useMapStore } from "@/lib/store";

const number = new Intl.NumberFormat("en-CA", { maximumFractionDigits: 0 });

const TABS: { tool: Exclude<Tool, "select">; label: string }[] = [
  { tool: "area", label: "Area" },
  { tool: "line", label: "Line" },
  { tool: "point", label: "Point" },
];

const AREA_TOOLS: { tool: AreaTool; label: string }[] = [
  { tool: "polygon", label: "Polygon" },
  { tool: "rectangle", label: "Rectangle" },
  { tool: "freehand", label: "Freehand" },
  { tool: "lot", label: "Lot" },
];

const HOW_TO: Record<AreaTool | "line" | "point", string[]> = {
  polygon: [
    "Click the map to place each corner",
    "Corners snap to nearby building and lot corners",
    "Click the first point, or press Enter, to close the shape; then drag corners to adjust",
  ],
  rectangle: ["Click one corner", "Move to size it, then click the opposite corner"],
  freehand: ["Click to start", "Move the mouse around the area", "Click again to finish"],
  lot: ["Click a lot to use its boundary"],
  line: [
    "Click points along the route; the line follows the streets",
    "Highways are avoided",
    "Double-click to finish",
  ],
  point: ["Click to place it", "It snaps onto a nearby street"],
};

function Label({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-fg-subtle">{children}</span>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <Label>{label}</Label>
      <p className="mt-1 text-lg font-semibold">{value}</p>
    </div>
  );
}

const km = (m: number) => (m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${number.format(m)} m`);
const areaText = (m2: number) =>
  m2 >= 10_000 ? `${(m2 / 10_000).toFixed(1)} ha` : `${number.format(m2)} m²`;

/** The drawing panel (design p7): the shape so far, how to draw, and Finish shape. */
export default function DrawPanel({ controller }: { controller: DrawController }) {
  const tool = useMapStore((s) => s.tool);
  const drawing = useMapStore((s) => s.drawing);
  const setTool = useMapStore((s) => s.setTool);
  if (tool === "select") return null;

  const g = drawing.geometry;
  const feature = g ? { type: "Feature" as const, properties: {}, geometry: g } : null;
  const isArea = g?.type === "Polygon" || g?.type === "MultiPolygon";
  const stats: [string, string][] =
    tool === "area"
      ? [
          ["Points", String(drawing.points)],
          ["Area", feature && isArea ? areaText(area(feature)) : "—"],
          ["Edge", feature && isArea ? km(length(feature, { units: "meters" })) : "—"],
        ]
      : tool === "line"
        ? [
            ["Stops", String(drawing.points)],
            ["Length", feature && g?.type === "LineString" ? km(length(feature, { units: "meters" })) : "—"],
            ["Streets", String(drawing.streets.length || "—")],
          ]
        : [["Placed", g ? "Yes" : "—"]];
  const howTo = HOW_TO[tool === "area" ? drawing.areaTool : tool];
  const check = drawing.check;
  const overlaps = check?.ok ? check.overlaps : [];

  return (
    <aside
      aria-label="Drawing"
      className="absolute right-4 top-4 z-20 flex w-[340px] max-w-[calc(100vw-32px)] flex-col rounded-panel border border-border bg-surface p-5 shadow-2xl shadow-black/40"
    >
      <header className="flex items-center justify-between">
        <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">
          <span className="size-2 bg-accent" />
          Drawing
        </p>
        <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-fg-subtle">Step 1 of 4</span>
      </header>

      <div role="tablist" className="mt-4 grid grid-cols-3 gap-1 rounded-control bg-surface-raised p-1">
        {TABS.map((t) => (
          <button
            key={t.tool}
            role="tab"
            type="button"
            aria-selected={tool === t.tool}
            onClick={() => setTool(t.tool)}
            className={`h-9 rounded-control text-sm ${
              tool === t.tool ? "border border-border-strong bg-bg text-fg" : "text-fg-muted hover:text-fg"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tool === "area" && (
        <div className="mt-3 flex flex-wrap gap-1.5" role="group" aria-label="Area tool">
          {AREA_TOOLS.map((t) => (
            <button
              key={t.tool}
              type="button"
              aria-pressed={drawing.areaTool === t.tool}
              onClick={() => setTool("area", t.tool)}
              className={`h-8 rounded-control border px-3 text-xs ${
                drawing.areaTool === t.tool
                  ? "border-accent text-fg"
                  : "border-border text-fg-muted hover:text-fg"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}

      <div className="mt-5 grid grid-cols-3 gap-3 border-b border-border pb-4">
        {stats.map(([label, value]) => (
          <Stat key={label} label={label} value={value} />
        ))}
      </div>

      <div className="mt-4">
        <Label>How to draw</Label>
        <ol className="mt-2 flex list-decimal flex-col gap-1 pl-5 text-sm text-fg-muted">
          {howTo.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </div>

      {drawing.streets.length > 0 && (
        <p className="mt-3 text-xs text-fg-muted">Follows {drawing.streets.slice(0, 4).join(", ")}</p>
      )}

      {(drawing.error || check) && (
        <div
          role={check && !check.ok ? "alert" : "status"}
          className={`mt-4 rounded-control border px-3 py-2.5 text-sm ${
            drawing.error || (check && !check.ok) ? "border-oppose/40" : "border-border bg-surface-raised"
          }`}
        >
          {drawing.error && <p>{drawing.error}</p>}
          {check?.errors.map((e) => (
            <p key={e}>{e}</p>
          ))}
          {overlaps.length > 0 && (
            <>
              <p className="text-fg">
                This overlaps {overlaps.length} building{overlaps.length === 1 ? "" : "s"}. Remove{" "}
                {overlaps.length === 1 ? "it" : "them"}?
              </p>
              <p className="mt-1 text-xs text-fg-muted">
                {overlaps
                  .slice(0, 3)
                  .map((o) => o.name ?? "Unnamed building")
                  .join(", ")}
                {overlaps.length > 3 ? ` and ${overlaps.length - 3} more` : ""}
              </p>
            </>
          )}
          {check?.ok &&
            check.warnings.map((w) => (
              <p key={w} className="mt-1 text-xs text-fg-muted">
                {w}
              </p>
            ))}
        </div>
      )}

      <footer className="mt-5 flex gap-2">
        <button
          type="button"
          onClick={() => setTool("select")}
          className="h-11 rounded-control border border-border-strong px-4 text-sm hover:bg-surface-raised"
        >
          Cancel
        </button>
        {overlaps.length > 0 ? (
          <button
            type="button"
            onClick={() => controller.accept()}
            className="h-11 flex-1 rounded-control bg-accent text-sm font-semibold text-accent-fg hover:brightness-95"
          >
            Remove {overlaps.length === 1 ? "it" : "them"} and continue
          </button>
        ) : (
          <button
            type="button"
            disabled={!drawing.complete || drawing.busy}
            onClick={() => void controller.finish()}
            className="flex h-11 flex-1 items-center justify-center gap-2 rounded-control bg-accent text-sm font-semibold text-accent-fg hover:brightness-95 disabled:opacity-40"
          >
            {drawing.busy && <Loader2 className="size-4 animate-spin" />}
            Finish shape
          </button>
        )}
      </footer>
    </aside>
  );
}

/** Key hints along the bottom of the map while drawing. */
export function DrawHints() {
  const tool = useMapStore((s) => s.tool);
  const areaTool = useMapStore((s) => s.drawing.areaTool);
  if (tool === "select") return null;
  const hints: [string, string][] =
    tool === "point" || (tool === "area" && areaTool === "lot")
      ? [
          ["Click", "place"],
          ["Esc", "cancel"],
        ]
      : [
          ["Click", "add point"],
          [tool === "line" ? "Double-click" : "Enter", "finish"],
          ["⌫", "undo point"],
          ["Esc", "cancel"],
        ];
  return (
    <div className="absolute bottom-6 left-1/2 z-10 flex -translate-x-1/2 items-center gap-4 rounded-panel border border-border-strong bg-surface px-4 py-2.5 text-sm text-fg-muted shadow-2xl shadow-black/40">
      {hints.map(([key, action]) => (
        <span key={key} className="flex items-center gap-1.5">
          <kbd className="rounded border border-border-strong px-1.5 py-0.5 font-mono text-xs text-fg">{key}</kbd>
          {action}
        </span>
      ))}
    </div>
  );
}
