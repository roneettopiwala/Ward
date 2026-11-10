"use client";

import type { Map as MapLibreMap, MapLayerMouseEvent } from "maplibre-gl";
import { useEffect, useState } from "react";

import { PERSONA_PINS_LAYER } from "@/lib/map-style";
import { useMapStore } from "@/lib/store";

export function km(m: number): string {
  return m < 100 ? "under 0.1 km" : `${(m / 1000).toFixed(1)} km`;
}

const LEGEND = [
  { label: "Supports", className: "bg-support" },
  { label: "Neutral", className: "bg-neutral" },
  { label: "Opposes", className: "bg-oppose" },
];

/** The legend for persona pins, and a "Name · 0.4 km" label on the hovered pin. */
export default function PersonaPins({ map }: { map: MapLibreMap }) {
  const cards = useMapStore((s) => (s.activeProposal ? s.analyses[s.activeProposal]?.personas : undefined));
  const [hovered, setHovered] = useState<string | null>(null);
  const [, redraw] = useState(0);

  useEffect(() => {
    const enter = (e: MapLayerMouseEvent) => {
      map.getCanvas().style.cursor = "pointer";
      setHovered(String(e.features?.[0]?.properties.id ?? ""));
    };
    const leave = () => {
      map.getCanvas().style.cursor = "";
      setHovered(null);
    };
    const move = () => redraw((n) => n + 1);
    map.on("mousemove", PERSONA_PINS_LAYER, enter);
    map.on("mouseleave", PERSONA_PINS_LAYER, leave);
    map.on("move", move);
    return () => {
      map.off("mousemove", PERSONA_PINS_LAYER, enter);
      map.off("mouseleave", PERSONA_PINS_LAYER, leave);
      map.off("move", move);
    };
  }, [map]);

  const focused = useMapStore((s) => s.focusedPersona);
  useEffect(() => {
    const pin = useMapStore
      .getState()
      .analyses[useMapStore.getState().activeProposal ?? ""]?.personas?.find((c) => c.persona.id === focused)?.pin;
    // Keep the focused pin in view, clear of the results panel on the right.
    if (pin) map.easeTo({ center: pin, padding: { right: 420, left: 0, top: 0, bottom: 0 }, duration: 600 });
  }, [map, focused]);

  if (!cards?.length) return null;
  const card = hovered ? cards.find((c) => c.persona.id === hovered) : undefined;
  const at = card ? map.project(card.pin) : null;

  return (
    <>
      <div className="pointer-events-none absolute left-[212px] top-4 z-10 flex h-12 items-center gap-3 rounded-panel border border-border bg-surface/90 px-4 backdrop-blur">
        <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-fg-subtle">Persona pins</span>
        {LEGEND.map((l) => (
          <span key={l.label} className="flex items-center gap-1.5 text-xs text-fg-muted">
            <span className={`size-2 rounded-full ${l.className}`} />
            {l.label}
          </span>
        ))}
      </div>
      {card && at && (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-[calc(100%+16px)] whitespace-nowrap rounded-control border border-border-strong bg-surface px-2 py-1 text-xs"
          style={{ left: at.x, top: at.y }}
        >
          {card.persona.name} · {km(card.distanceM)}
        </div>
      )}
    </>
  );
}
