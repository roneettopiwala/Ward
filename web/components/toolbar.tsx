"use client";

import { MapPin, MousePointer2, Pentagon, Spline, Undo2 } from "lucide-react";
import { useEffect } from "react";

import { useMapStore } from "@/lib/store";

const toolClass =
  "flex size-10 items-center justify-center rounded-control text-fg-muted disabled:opacity-35";

/** Floating tool rail. Only Select and Undo work in Phase 1; drawing comes in Phase 6. */
export default function Toolbar() {
  const canUndo = useMapStore((s) => s.history.length > 0);
  const undo = useMapStore((s) => s.undo);
  const select = useMapStore((s) => s.select);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z" && !e.shiftKey) {
        e.preventDefault();
        undo();
      } else if (e.key === "Escape") {
        select(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, select]);

  return (
    <nav
      aria-label="Map tools"
      className="absolute left-4 top-[88px] z-10 flex flex-col gap-1 rounded-panel border border-border bg-surface p-1"
    >
      <button
        type="button"
        aria-label="Select"
        aria-pressed
        className={`${toolClass} border border-border-strong bg-surface-raised text-accent`}
      >
        <MousePointer2 className="size-4" />
      </button>
      <button type="button" aria-label="Draw area" disabled className={toolClass}>
        <Pentagon className="size-4" />
      </button>
      <button type="button" aria-label="Draw line" disabled className={toolClass}>
        <Spline className="size-4" />
      </button>
      <button type="button" aria-label="Place point" disabled className={toolClass}>
        <MapPin className="size-4" />
      </button>
      <hr className="mx-2 my-1 border-border" />
      <button
        type="button"
        aria-label="Undo"
        title="Undo (Ctrl+Z)"
        disabled={!canUndo}
        onClick={undo}
        className={`${toolClass} hover:bg-surface-raised hover:text-fg`}
      >
        <Undo2 className="size-4" />
      </button>
    </nav>
  );
}
