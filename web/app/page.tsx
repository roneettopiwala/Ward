import { Box } from "lucide-react";

import MapView from "@/components/map-view";
import Toolbar from "@/components/toolbar";

export default function Home() {
  return (
    <main className="relative h-dvh w-full overflow-hidden bg-bg">
      <MapView />

      <header className="absolute left-4 top-4 z-10 flex h-12 items-center gap-3 rounded-panel border border-border bg-surface px-4">
        <Box className="size-5" strokeWidth={1.5} />
        <span className="font-semibold">Ward</span>
        <span className="h-4 w-px bg-border-strong" />
        <span className="font-mono text-xs text-fg-muted">Toronto</span>
      </header>

      <Toolbar />

      {/* The results side panel docks on the right edge from Phase 3. */}
    </main>
  );
}
