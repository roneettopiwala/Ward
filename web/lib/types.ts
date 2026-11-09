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
export type Proposal = {
  id: string;
  type: string;
  params: Record<string, number>;
  geometry: Geometry;
  replaces: Fid[];
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

export type AnalysisStatus = "creating" | "analyzing" | "writing" | "done" | "error";

/** A proposal's analysis as it streams in from the API. */
export type Analysis = {
  status: AnalysisStatus;
  serverId?: string;
  factSheet?: FactSheet;
  pros?: ProCon[];
  cons?: ProCon[];
  error?: string;
};
