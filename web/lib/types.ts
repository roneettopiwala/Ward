import type { Geometry, MultiPolygon, Polygon } from "geojson";

/** Stable Ward feature id, e.g. "building:79697012". */
export type Fid = string;

/** A base-map feature as the rest of the app sees it (no basemap ids). */
export type BaseFeature = {
  fid: Fid;
  name: string | null;
  use: string | null;
  heightM: number | null;
  footprint: Polygon | MultiPolygon;
};

/**
 * A proposed change. Plain data so a parsed prompt can create one later.
 * Geometry may be any type: areas, lines and points are all coming.
 */
export type Proposal = {
  id: string;
  type: string;
  params: Record<string, unknown>;
  geometry: Geometry;
  replaces: Fid[];
};
