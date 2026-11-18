import type {
  BaseFeature,
  CatalogParam,
  CatalogType,
  ContextCard,
  DrawRules,
  DrawTool,
  Fact,
  FactSheet,
  FeatureKind,
  Fid,
  Geometry,
  ParseResult,
  Part,
  PersonaCard,
  ProCon,
  Proposal,
  Sentiment,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type FeatureDetailResponse = {
  fid: string;
  kind: FeatureKind;
  name: string | null;
  use: string | null;
  height_m: number | null;
  address: string | null;
  lot_area_m2: number | null;
  zoning: { code: string; zone_class: string | null; max_height_m: number | null } | null;
  nearest_stops: {
    fid: string;
    name: string | null;
    mode: string | null;
    routes: string[];
    distance_m: number;
  }[];
  mode: string | null;
  routes: string[];
  road_class: string | null;
  facility_type: string | null;
  installed: number | null;
  length_m: number | null;
  geometry: Geometry;
};

/** Any map feature with its details; null when it isn't in our data. */
export async function featureDetail(fid: Fid): Promise<BaseFeature | null> {
  const res = await fetch(`${API_URL}/features/${encodeURIComponent(fid)}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`features/${fid}: HTTP ${res.status}`);
  const d = (await res.json()) as FeatureDetailResponse;
  return {
    fid: d.fid,
    kind: d.kind,
    name: d.name,
    use: d.use,
    heightM: d.height_m,
    geometry: d.geometry,
    details: {
      address: d.address,
      lotAreaM2: d.lot_area_m2,
      zoning: d.zoning && {
        code: d.zoning.code,
        zoneClass: d.zoning.zone_class,
        maxHeightM: d.zoning.max_height_m,
      },
      nearestStops: d.nearest_stops.map((s) => ({
        fid: s.fid,
        name: s.name,
        mode: s.mode,
        routes: s.routes,
        distanceM: s.distance_m,
      })),
      mode: d.mode,
      routes: d.routes,
      roadClass: d.road_class,
      facilityType: d.facility_type,
      installed: d.installed,
      lengthM: d.length_m,
    },
  };
}

type CatalogResponse = {
  type: string;
  label: string;
  geometry: CatalogType["geometry"];
  params: Record<string, CatalogParam>;
  render: { kind: CatalogType["render"]["kind"]; color: string; height_param: string | null };
  impact_radius_m: number;
  storey_m: number | null;
  draw: {
    tools: DrawTool[];
    min_area_m2: number | null;
    max_area_m2: number | null;
    min_length_m: number | null;
    max_length_m: number | null;
    snap: DrawRules["snap"];
  };
}[];

export type ParseRequest = {
  prompt: string;
  geometryType: string;
  selection: {
    name: string | null;
    use: string | null;
    heightM: number | null;
    lotAreaM2: number | null;
    zoning: string | null;
  };
  /** The proposal being changed, for follow-up prompts. */
  current?: Part[];
};

/** Turn a typed prompt into proposal parts. Throws with the API's message on failure. */
export async function parsePrompt(req: ParseRequest): Promise<ParseResult> {
  const res = await fetch(`${API_URL}/proposals/parse`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      prompt: req.prompt,
      geometry_type: req.geometryType,
      selection: {
        name: req.selection.name,
        use: req.selection.use,
        height_m: req.selection.heightM,
        lot_area_m2: req.selection.lotAreaM2,
        zoning: req.selection.zoning,
      },
      current: req.current,
    }),
  });
  if (!res.ok) {
    const detail = ((await res.json().catch(() => ({}))) as { detail?: unknown }).detail;
    throw new Error(typeof detail === "string" ? detail : `HTTP ${res.status}`);
  }
  const r = (await res.json()) as {
    parts: Part[];
    replaces_existing: boolean;
    assumptions: string[];
    clarification: string | null;
  };
  return {
    parts: r.parts,
    replacesExisting: r.replaces_existing,
    assumptions: r.assumptions,
    clarification: r.clarification,
  };
}

export async function fetchCatalog(): Promise<CatalogType[]> {
  const res = await fetch(`${API_URL}/catalog`);
  if (!res.ok) throw new Error(`catalog: HTTP ${res.status}`);
  const types = (await res.json()) as CatalogResponse;
  return types.map((t) => ({
    type: t.type,
    label: t.label,
    geometry: t.geometry,
    params: t.params,
    render: { kind: t.render.kind, color: t.render.color, heightParam: t.render.height_param },
    impactRadiusM: t.impact_radius_m,
    storeyM: t.storey_m,
    draw: {
      tools: t.draw.tools,
      minAreaM2: t.draw.min_area_m2,
      maxAreaM2: t.draw.max_area_m2,
      minLengthM: t.draw.min_length_m,
      maxLengthM: t.draw.max_length_m,
      snap: t.draw.snap,
    },
  }));
}

export type Route = {
  geometry: Geometry;
  lengthM: number;
  streets: string[];
  /** Each clicked point, moved to the intersection the route uses. */
  waypoints: [number, number][];
};

/** A line along the streets through the points, in order. Throws with the API's message. */
export async function routeLine(points: [number, number][], signal?: AbortSignal): Promise<Route> {
  const res = await fetch(`${API_URL}/draw/route`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ points }),
    signal,
  });
  if (!res.ok) throw new Error(await errorMessage(res, "Couldn't route that line."));
  const d = (await res.json()) as { geometry: Geometry; length_m: number; streets: string[]; waypoints: [number, number][] };
  return { geometry: d.geometry, lengthM: d.length_m, streets: d.streets, waypoints: d.waypoints };
}

export type ShapeCheck = {
  ok: boolean;
  errors: string[];
  warnings: string[];
  areaM2: number | null;
  lengthM: number | null;
  /** Buildings the shape covers. */
  overlaps: { fid: Fid; name: string | null }[];
  parks: string[];
};

/** Check a drawn shape: size, inside Toronto, off water and highways, what it covers. */
export async function validateShape(geometry: Geometry, type?: string): Promise<ShapeCheck> {
  const res = await fetch(`${API_URL}/draw/validate`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ geometry, type }),
  });
  if (!res.ok) throw new Error(await errorMessage(res, "Couldn't check that shape."));
  const d = (await res.json()) as {
    ok: boolean;
    errors: string[];
    warnings: string[];
    area_m2: number | null;
    length_m: number | null;
    overlaps: { fid: Fid; name: string | null }[];
    parks: string[];
  };
  return {
    ok: d.ok,
    errors: d.errors,
    warnings: d.warnings,
    areaM2: d.area_m2,
    lengthM: d.length_m,
    overlaps: d.overlaps,
    parks: d.parks,
  };
}

async function errorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : fallback;
  } catch {
    return fallback;
  }
}

/** Store a proposal; returns the server's id. */
/** Store a proposal; `parentServerId` links a new version to the one it changes. */
export async function createProposal(p: Proposal, parentServerId?: string): Promise<string> {
  const res = await fetch(`${API_URL}/proposals`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      // The API picks the main part for type/params; components carry every part.
      type: p.parts[0].type,
      params: p.parts[0].params,
      components: p.parts,
      geometry: p.geometry,
      replaces: p.replaces,
      prompt: p.prompt,
      parent_id: parentServerId ?? null,
    }),
  });
  if (!res.ok) {
    const detail = ((await res.json().catch(() => ({}))) as { detail?: unknown }).detail;
    throw new Error(typeof detail === "string" ? detail : `HTTP ${res.status}`);
  }
  return ((await res.json()) as { id: string }).id;
}

type FactSheetEvent = {
  type_label: string;
  site_name: string;
  impact_radius_m: number;
  facts: Fact[];
};

type PersonaCardEvent = {
  persona: Omit<PersonaCard["persona"], "basedOn"> & { based_on: string | null };
  pin: [number, number];
  distance_m: number;
  bullets: string[];
  stance: number;
  stance_label: PersonaCard["stanceLabel"];
  reasons: string[];
  quote: string;
  themes: string[];
};

type ContextCardEvent = {
  neighbourhood_id: number;
  name: string;
  people: string[];
  developments_summary: string;
  recent_developments: ContextCard["recentDevelopments"];
  places: string[];
  anchors: string[];
  themes: string[];
  themes_comments: number;
  themes_scope: string;
};

export type AnalysisHandlers = {
  status: (status: string) => void;
  factSheet: (sheet: FactSheet) => void;
  context: (cards: ContextCard[]) => void;
  prosCons: (pros: ProCon[], cons: ProCon[]) => void;
  personas: (total: number) => void;
  persona: (card: PersonaCard) => void;
  sentiment: (sentiment: Sentiment) => void;
  done: () => void;
  error: (message: string) => void;
};

/** Follow a proposal's analysis over server-sent events. Returns a function that stops it. */
export function streamAnalysis(serverId: string, on: AnalysisHandlers): () => void {
  const source = new EventSource(`${API_URL}/proposals/${serverId}/events`);
  const data = <T>(e: Event) => JSON.parse((e as MessageEvent<string>).data) as T;
  let finished = false;

  source.addEventListener("status", (e) => on.status(data<{ status: string }>(e).status));
  source.addEventListener("fact_sheet", (e) => {
    const s = data<FactSheetEvent>(e);
    on.factSheet({
      typeLabel: s.type_label,
      siteName: s.site_name,
      impactRadiusM: s.impact_radius_m,
      facts: s.facts.map(({ id, label, display, source }) => ({ id, label, display, source })),
    });
  });
  source.addEventListener("context", (e) =>
    on.context(
      data<{ cards: ContextCardEvent[] }>(e).cards.map((c) => ({
        neighbourhoodId: c.neighbourhood_id,
        name: c.name,
        people: c.people,
        developmentsSummary: c.developments_summary,
        recentDevelopments: c.recent_developments,
        places: c.places,
        anchors: c.anchors,
        themes: c.themes,
        themesComments: c.themes_comments,
        themesScope: c.themes_scope,
      })),
    ),
  );
  source.addEventListener("pros_cons", (e) => {
    const r = data<{ pros: ProCon[]; cons: ProCon[] }>(e);
    on.prosCons(r.pros, r.cons);
  });
  source.addEventListener("personas", (e) => on.personas(data<{ total: number }>(e).total));
  source.addEventListener("persona", (e) => {
    const c = data<PersonaCardEvent>(e);
    on.persona({
      persona: {
        id: c.persona.id,
        name: c.persona.name,
        age: c.persona.age,
        role: c.persona.role,
        occupation: c.persona.occupation,
        tagline: c.persona.tagline,
        basedOn: c.persona.based_on,
      },
      pin: c.pin,
      distanceM: c.distance_m,
      bullets: c.bullets,
      stance: c.stance,
      stanceLabel: c.stance_label,
      reasons: c.reasons,
      quote: c.quote,
      themes: c.themes,
    });
  });
  source.addEventListener("sentiment", (e) => on.sentiment(data<Sentiment>(e)));
  source.addEventListener("done", () => {
    finished = true;
    source.close();
    on.done();
  });
  // Named "error" events carry a message; a bare error is the connection failing.
  source.addEventListener("error", (e) => {
    if (finished) return;
    finished = true;
    source.close();
    const message = e instanceof MessageEvent ? data<{ message: string }>(e).message : null;
    on.error(message ?? "Lost connection to the API.");
  });
  return () => {
    finished = true;
    source.close();
  };
}
