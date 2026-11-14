"use client";

import { MapPin, MousePointer2, Pentagon, Spline, Undo2 } from "lucide-react";
import { useEffect } from "react";

import { type Tool, useMapStore } from "@/lib/store";

const toolClass =
  "flex size-10 items-center justify-center rounded-control text-fg-muted disabled:opacity-35";

const TOOLS: { tool: Tool; label: string; key: string; Icon: typeof MousePointer2 }[] = [
  { tool: "select", label: "Select", key: "V", Icon: MousePointer2 },
  { tool: "area", label: "Draw area", key: "A", Icon: Pentagon },
  { tool: "line", label: "Draw line", key: "L", Icon: Spline },
  { tool: "point", label: "Place point", key: "P", Icon: MapPin },
];

/** Floating tool rail: select, the three drawing tools, and undo. */
export default function Toolbar() {
  const canUndo = useMapStore((s) => s.history.length > 0);
  const undo = useMapStore((s) => s.undo);
  const tool = useMapStore((s) => s.tool);
  const setTool = useMapStore((s) => s.setTool);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      const { tool: current, setTool: set, select } = useMapStore.getState();
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z" && !e.shiftKey) {
        // While drawing, Ctrl+Z belongs to the shape (Backspace also undoes a point).
        if (current !== "select") return;
        e.preventDefault();
        undo();
      } else if (e.key === "Escape") {
        if (current !== "select") set("select");
        else select(null);
      } else if (!e.metaKey && !e.ctrlKey && !e.altKey) {
        const picked = TOOLS.find((t) => t.key.toLowerCase() === e.key.toLowerCase());
        if (picked && picked.tool !== current) set(picked.tool);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo]);

  return (
    <nav
      aria-label="Map tools"
      className="absolute left-4 top-[88px] z-10 flex flex-col gap-1 rounded-panel border border-border bg-surface p-1"
    >
      {TOOLS.map(({ tool: t, label, key, Icon }) => (
        <button
          key={t}
          type="button"
          aria-label={label}
          aria-pressed={tool === t}
          aria-keyshortcuts={key}
          title={`${label} (${key})`}
          onClick={() => setTool(t)}
          className={`${toolClass} ${
            tool === t
              ? "border border-border-strong bg-surface-raised text-accent"
              : "hover:bg-surface-raised hover:text-fg"
          }`}
        >
          <Icon className="size-4" />
        </button>
      ))}
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
