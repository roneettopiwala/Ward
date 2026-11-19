import type { Geometry } from "geojson";

export type { Geometry };

/** Stable Ward feature id, e.g. "building:79697012". */
export type Fid = string;

/** Every kind of map feature, from its fid prefix ("park:123"); "drawn" is a shape the user drew. */
export type FeatureKind = "building" | "parcel" | "park" | "transit" | "cycling" | "street" | "drawn";

/** Kinds a proposal can go on; existing lines and points are shown for information. */
export const REPLACEABLE: readonly FeatureKind[] = ["building", "parcel", "park", "drawn"];

/** A map feature as the rest of the app sees it. */
export type BaseFeature = {
  fid: Fid;
  kind: FeatureKind;
  name: string | null;
  use: string | null;
  heightM: number | null;
  geometry: Geometry;
  /** From our database (the tiles carry only a few properties). */
  details?: FeatureDetails;
  /** A drawn shape: the buildings the user agreed to remove for it, and its checks. */
  drawn?: DrawnSite;
};

export type DrawnSite = {
  replaces: Fid[];
  areaM2: number | null;
  lengthM: number | null;
  /** Streets a routed line follows. */
  streets: string[];
  warnings: string[];
};

export type FeatureDetails = {
  address: string | null;
  /** A building's lot, or a parcel's or park's own area. */
  lotAreaM2: number | null;
  /** Null where Zoning By-law 569-2013 does not apply. */
  zoning: Zoning | null;
  nearestStops: TransitStop[];
  mode: string | null;
  routes: string[];
  roadClass: string | null;
  facilityType: string | null;
  installed: number | null;
  lengthM: number | null;
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

/** Where a selection is in loading its details. */
export type SelectionStatus = "loading" | "ready" | "not-found" | "error";

/**
 * A proposed change. Plain data so a parsed prompt can create one later.
 * Geometry may be any type: areas, lines and points are all coming.
 */
/** One part of a proposal (a catalog type with its params), e.g. a retail podium. */
export type Part = {
  /** The catalog class, e.g. "residential". */
  type: string;
  /** A subtype id ("townhouses"), a free-text name ("cat café"), or null for the class default. */
  subtype?: string | null;
  params: Record<string, number>;
  /** What it is beyond its catalog type, e.g. ["food hall"]. */
  tags: string[];
};

export type Proposal = {
  id: string;
  /** Bottom to top; a flat part (park) sits on the roof when there are several. */
  parts: Part[];
  geometry: Geometry;
  /** The selected or drawn site it was built on. */
  siteFid: Fid;
  /** Base features it removes (the site itself, or buildings under a drawn shape). */
  replaces: Fid[];
  /** What the user typed, when it came from the prompt bar. */
  prompt: string | null;
  assumptions: string[];
  /** The version this one changes, and its number (1 for a first proposal). */
  parentId: string | null;
  version: number;
};

/** A buildable type from the catalog (api/catalog/*.yaml). */
/** One class and subtype as the API resolves it (class fields with the subtype's overrides). */
export type CatalogType = {
  /** The class id. */
  type: string;
  subtype: string | null;
  defaultSubtype: string;
  /** The subtype's label, e.g. "Townhouses". */
  label: string;
  /** The class's label, e.g. "Residential". */
  classLabel: string;
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
  draw: DrawRules;
};

export type DrawTool = "lot" | "rectangle" | "polygon" | "freehand" | "route" | "point";

export type DrawRules = {
  tools: DrawTool[];
  minAreaM2: number | null;
  maxAreaM2: number | null;
  minLengthM: number | null;
  maxLengthM: number | null;
  snap: "vertices" | "street" | "none";
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
    role: "resident" | "worker" | "visitor" | "citywide";
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

/** A neighbourhood's context card: who lives there, recent developments, places, concerns. */
export type ContextCard = {
  neighbourhoodId: number;
  name: string;
  people: string[];
  developmentsSummary: string;
  recentDevelopments: { address: string; submitted: string; status: string; summary: string }[];
  places: string[];
  /** Named places: the largest parks and rapid transit stations. */
  anchors: string[];
  /** What residents most often raised at past consultations, most common first. */
  themes: string[];
  themesComments: number;
  /** "this neighbourhood", "within 3 km", or "" when there are no comments. */
  themesScope: string;
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
  /** Context cards for the neighbourhoods personas come from, most affected first. */
  context?: ContextCard[];
  pros?: ProCon[];
  cons?: ProCon[];
  /** How many personas are reacting, once they're chosen. */
  personaTotal?: number;
  personas?: PersonaCard[];
  sentiment?: Sentiment;
  error?: string;
};
