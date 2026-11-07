"use client";

import { Minus, Plus } from "lucide-react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useState } from "react";

import { basemapAttribution } from "@/lib/basemap";

const PITCH_3D = 45;

const buttonClass =
  "flex size-10 items-center justify-center rounded-control text-fg-muted hover:bg-surface-raised hover:text-fg";

/** Zoom and 2D/2.5D controls, bottom left, plus the attribution line. */
export default function MapControls({ map }: { map: MapLibreMap }) {
  const [pitched, setPitched] = useState(map.getPitch() > 0);

  useEffect(() => {
    const onPitch = () => setPitched(map.getPitch() > 0);
    map.on("pitchend", onPitch);
    return () => {
      map.off("pitchend", onPitch);
    };
  }, [map]);

  return (
    <>
      <div className="absolute bottom-12 left-4 z-10 flex flex-col gap-1 rounded-panel border border-border bg-surface p-1">
        <button type="button" aria-label="Zoom in" className={buttonClass} onClick={() => map.zoomIn()}>
          <Plus className="size-4" />
        </button>
        <button type="button" aria-label="Zoom out" className={buttonClass} onClick={() => map.zoomOut()}>
          <Minus className="size-4" />
        </button>
        <button
          type="button"
          aria-label={pitched ? "Switch to flat 2D view" : "Switch to 2.5D view"}
          onClick={() => map.easeTo({ pitch: pitched ? 0 : PITCH_3D })}
          className="flex size-10 items-center justify-center rounded-control bg-surface-raised font-mono text-xs text-accent"
        >
          {pitched ? "2.5D" : "2D"}
        </button>
      </div>
      <p className="absolute bottom-3 left-4 z-10 font-mono text-[10px] text-fg-subtle">
        {basemapAttribution}
      </p>
    </>
  );
}
