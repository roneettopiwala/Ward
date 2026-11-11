import type { Geometry, MultiPolygon, Polygon } from "geojson";

export type { Geometry };

/** Stable Ward feature id, e.g. "building:79697012". */
export type Fid = string;

/** A base-map feature as the rest of the app sees it (no basemap ids). */
export type BaseFeature = {
  fid: Fid;
  name: string | null;
  use: string | null;
  heightM: number | null;
  footprint: Polygon | MultiPolygon;
  /** From our database; absent outside the loaded area. */
  details?: FeatureDetails;
};

export type FeatureDetails = {
  address: string | null;
  lotAreaM2: number | null;
  /** Null where Zoning By-law 569-2013 does not apply. */
  zoning: Zoning | null;
  nearestStops: TransitStop[];
};

export type Zoning = {
  code: string;
  zoneClass: string | null;
  maxHeightM: number | null;
};

export type TransitStop = {
  fid: Fid;
  name: string | null;
  mode: string | null;
  routes: string[];
  distanceM: number;
};

/** Where a selection is in being matched to our data. */
export type SelectionStatus = "loading" | "ready" | "outside-area" | "not-found" | "error";

/**
 * A proposed change. Plain data so a parsed prompt can create one later.
 * Geometry may be any type: areas, lines and points are all coming.
 */
/** One part of a proposal (a catalog type with its params), e.g. a retail podium. */
export type Part = {
  type: string;
  params: Record<string, number>;
  /** What it is beyond its catalog type, e.g. ["food hall"]. */
  tags: string[];
};

export type Proposal = {
  id: string;
  /** Bottom to top; a flat part (park) sits on the roof when there are several. */
  parts: Part[];
  geometry: Geometry;
  replaces: Fid[];
  /** What the user typed, when it came from the prompt bar. */
  prompt: string | null;
  assumptions: string[];
  /** The version this one changes, and its number (1 for a first proposal). */
  parentId: string | null;
  version: number;
};

/** A buildable type from the catalog (api/catalog/*.yaml). */
export type CatalogType = {
  type: string;
  label: string;
  geometry: "polygon" | "line" | "point";
  params: Record<string, CatalogParam>;
  render: {
    kind: "extrusion" | "flat" | "line" | "point";
    /** A map token name, e.g. "accent" or "proposalPark". */
    color: string;
    heightParam: string | null;
  };
  impactRadiusM: number;
  /** Metres per storey, for types with a height. */
  storeyM: number | null;
};

export type CatalogParam = {
  label: string;
  unit: string | null;
  default: number;
  min: number;
  max: number;
  step: number;
  main: boolean;
};

/** One computed fact; every number in the results panel comes from one. */
export type Fact = {
  id: string;
  label: string;
  display: string;
  source: string;
};

export type FactSheet = {
  typeLabel: string;
  siteName: string;
  impactRadiusM: number;
  facts: Fact[];
};

export type ProCon = {
  text: string;
  /** Ids of the facts the claim rests on. */
  facts: string[];
  sources: string[];
};

export type Stance = "supports" | "neutral" | "opposes";

/** One persona's reaction: who they are, how the proposal touches them, what they say. */
export type PersonaCard = {
  persona: {
    id: string;
    name: string;
    age: number;
    role: "resident" | "worker" | "visitor";
    occupation: string;
    tagline: string;
    basedOn: string | null;
  };
  /** Where the persona shows on the map, and how far that is from the site. */
  pin: [number, number];
  distanceM: number;
  /** Personal impact computed in code: "What shapes this view". */
  bullets: string[];
  stance: number;
  stanceLabel: Stance;
  reasons: string[];
  quote: string;
  themes: string[];
};

export type Sentiment = {
  count: number;
  mean: number;
  /** Shares of personas, 0..1. */
  support: number;
  neutral: number;
  oppose: number;
  label: string;
  themes: { theme: string; count: number; support: number; oppose: number }[];
};

/** The prompt parser's reading of what the user typed. */
export type ParseResult = {
  parts: Part[];
  replacesExisting: boolean;
  assumptions: string[];
  /** Set (with no parts) when the parser needs a question answered. */
  clarification: string | null;
};

export type AnalysisStatus = "creating" | "analyzing" | "writing" | "personas" | "done" | "error";

/** A proposal's analysis as it streams in from the API. */
export type Analysis = {
  status: AnalysisStatus;
  serverId?: string;
  factSheet?: FactSheet;
  pros?: ProCon[];
  cons?: ProCon[];
  /** How many personas are reacting, once they're chosen. */
  personaTotal?: number;
  personas?: PersonaCard[];
  sentiment?: Sentiment;
  error?: string;
};
