/**
 * Drawing on the map: areas (a lot, a rectangle, a polygon or freehand),
 * lines routed along streets, and points snapped to a street.
 *
 * Areas use Terra Draw, with corners snapping to nearby building and lot
 * corners. Lines and points are simple enough to handle here: each click adds
 * a waypoint and the server routes the line along the streets.
 */
import nearestPointOnLine from "@turf/nearest-point-on-line";
import type { GeoJSONSource, Map as MapLibreMap, MapMouseEvent } from "maplibre-gl";
import {
  TerraDraw,
  TerraDrawFreehandMode,
  TerraDrawModeUndoRedo,
  TerraDrawPolygonMode,
  TerraDrawRectangleMode,
  TerraDrawRenderMode,
  type HexColor,
  type SnapToCustom,
} from "terra-draw";
import { TerraDrawMapLibreGLAdapter } from "terra-draw-maplibre-gl-adapter";

import { featureDetail, routeLine, validateShape } from "./api";
import { featuresAt } from "./city-layers";
import { DRAW_LINE_SOURCE, DRAW_POINTS_SOURCE, toCollection } from "./map-style";
import { type AreaTool, useMapStore } from "./store";
import type { MapTokens } from "./tokens";
import type { BaseFeature, Geometry } from "./types";

/** Corners snap to building and lot corners within this many pixels. */
const SNAP_PX = 10;
/** A point snaps to a street within this many pixels. */
const STREET_SNAP_PX = 40;
const SNAP_LAYERS = ["city-buildings-3d", "city-parcels-hit"];
/** A click this close to the last waypoint is part of a double-click, not a new point. */
const SAME_SPOT_PX = 12;

type LngLat = [number, number];

/**
 * One controller per map. It follows the store's tool: Terra Draw runs while
 * the area tool (other than "lot") is active; clicks drive lines and points.
 */
export class DrawController {
  private draw: TerraDraw | null = null;
  private waypoints: LngLat[] = [];
  private routeAbort: AbortController | null = null;
  private unsubscribe: () => void;

  constructor(
    private map: MapLibreMap,
    private tokens: MapTokens,
  ) {
    this.unsubscribe = useMapStore.subscribe((s, prev) => {
      if (s.tool !== prev.tool || s.drawing.areaTool !== prev.drawing.areaTool) this.reset();
    });
    this.reset();
  }

  dispose(): void {
    this.unsubscribe();
    this.stopTerraDraw();
  }

  /** Map clicks while a drawing tool is on. Returns true when the click was used. */
  handleClick(e: MapMouseEvent): boolean {
    const { tool, drawing } = useMapStore.getState();
    if (tool === "select") return false;
    if (tool === "area" && drawing.areaTool === "lot") void this.pickLot(e);
    if (tool === "line") void this.addWaypoint([e.lngLat.lng, e.lngLat.lat]);
    if (tool === "point") this.placePoint(e);
    // Terra Draw handles area clicks itself.
    return true;
  }

  handleDoubleClick(e: MapMouseEvent): void {
    if (useMapStore.getState().tool === "line") {
      e.preventDefault();
      if (this.waypoints.length >= 2) useMapStore.getState().patchDrawing({ complete: true });
    }
  }

  /** Backspace: take back the last corner or waypoint. */
  undoPoint(): void {
    const { tool } = useMapStore.getState();
    if (tool === "area") this.draw?.undo();
    if (tool === "line" && this.waypoints.length) {
      this.waypoints.pop();
      void this.reroute();
    }
  }

  /** Check the shape; with no problems and nothing to remove, it becomes the site. */
  async finish(): Promise<void> {
    const { drawing, patchDrawing } = useMapStore.getState();
    if (!drawing.geometry || drawing.busy) return;
    patchDrawing({ busy: true, error: null });
    try {
      const check = await validateShape(drawing.geometry);
      patchDrawing({ busy: false, check });
      if (check.ok && check.overlaps.length === 0) this.accept();
    } catch (err) {
      patchDrawing({ busy: false, error: (err as Error).message });
    }
  }

  /** Use the shape as the site, removing the buildings it covers. */
  accept(): void {
    const { drawing, finishDrawing } = useMapStore.getState();
    const check = drawing.check;
    if (!drawing.geometry || !check?.ok) return;
    const type = drawing.geometry.type;
    const name =
      type === "LineString"
        ? drawing.streets.length
          ? `Line along ${drawing.streets[0]}`
          : "New line"
        : type === "Point"
          ? "New point"
          : "Drawn area";
    const site: BaseFeature = {
      fid: `drawn:${crypto.randomUUID()}`,
      kind: "drawn",
      name,
      use: null,
      heightM: null,
      geometry: drawing.geometry,
      drawn: {
        replaces: check.overlaps.map((o) => o.fid),
        areaM2: check.areaM2,
        lengthM: check.lengthM,
        streets: drawing.streets,
        warnings: check.warnings,
      },
    };
    finishDrawing(site);
  }

  // ------------------------------------------------------------ state

  private reset(): void {
    const { tool, drawing } = useMapStore.getState();
    this.waypoints = [];
    this.routeAbort?.abort();
    this.setPreview(null, []);
    const areaTool = drawing.areaTool;
    if (tool === "area" && areaTool !== "lot") this.startTerraDraw(areaTool);
    else this.stopTerraDraw();
    this.map.getCanvas().style.cursor = tool === "select" ? "" : "crosshair";
    this.map.doubleClickZoom[tool === "line" ? "disable" : "enable"]();
  }

  private setPreview(line: Geometry | null, points: LngLat[]): void {
    this.map.getSource<GeoJSONSource>(DRAW_LINE_SOURCE)?.setData(toCollection(line ? [line] : []));
    this.map
      .getSource<GeoJSONSource>(DRAW_POINTS_SOURCE)
      ?.setData(toCollection(points.map((coordinates) => ({ type: "Point", coordinates }))));
  }

  // ------------------------------------------------------------ areas

  private startTerraDraw(areaTool: Exclude<AreaTool, "lot">): void {
    if (!this.draw) {
      const accent = this.tokens.accent as HexColor;
      const styles = {
        fillColor: accent,
        fillOpacity: 0.18,
        outlineColor: accent,
        outlineWidth: 2,
      };
      const snapping = { toCustom: this.snapToCorner, showSnappingPoint: true };
      this.draw = new TerraDraw({
        adapter: new TerraDrawMapLibreGLAdapter({ map: this.map }),
        modes: [
          new TerraDrawPolygonMode({
            snapping,
            editable: true,
            showCoordinatePoints: true,
            keyEvents: { cancel: null, finish: "Enter" },
            styles: {
              ...styles,
              closingPointColor: accent,
              closingPointWidth: 7,
              closingPointOutlineColor: "#000000",
              coordinatePointColor: accent,
              coordinatePointWidth: 5,
              snappingPointColor: "#ffffff",
              snappingPointWidth: 5,
            },
          }),
          new TerraDrawRectangleMode({ styles }),
          new TerraDrawFreehandMode({ styles, keyEvents: { cancel: null, finish: "Enter" } }),
          new TerraDrawRenderMode({ modeName: "static", styles: {} }),
        ],
        undoRedo: { modeLevel: new TerraDrawModeUndoRedo() },
      });
      this.draw.on("change", () => this.onAreaChange());
      this.draw.on("finish", (id) => this.onAreaFinish(String(id)));
    }
    if (!this.draw.enabled) this.draw.start();
    this.draw.clear();
    this.draw.setMode(areaTool);
  }

  private stopTerraDraw(): void {
    if (this.draw?.enabled) {
      this.draw.clear();
      this.draw.stop();
    }
  }

  private onAreaChange(): void {
    const polygon = this.draw?.getSnapshot().find((f) => f.geometry.type === "Polygon");
    if (!polygon || polygon.geometry.type !== "Polygon") return;
    const ring = polygon.geometry.coordinates[0];
    const { drawing, patchDrawing } = useMapStore.getState();
    // While drawing, the ring repeats its first corner and follows the cursor.
    const corners = Math.max(0, ring.length - (drawing.complete ? 1 : 2));
    patchDrawing({ geometry: polygon.geometry, points: corners, check: null });
  }

  private onAreaFinish(id: string): void {
    const draw = this.draw;
    if (!draw) return;
    // One shape at a time: drop any earlier one.
    const others = draw.getSnapshot().filter((f) => String(f.id) !== id);
    if (others.length) draw.removeFeatures(others.map((f) => f.id!));
    const feature = draw.getSnapshotFeature(id);
    if (feature?.geometry.type !== "Polygon") return;
    useMapStore.getState().patchDrawing({
      geometry: feature.geometry,
      points: feature.geometry.coordinates[0].length - 1,
      complete: true,
      check: null,
    });
  }

  /** Snap a corner to the nearest building or lot corner on screen. */
  private snapToCorner: SnapToCustom = (event) => {
    const { containerX: x, containerY: y } = event;
    const hits = this.map.queryRenderedFeatures(
      [
        [x - SNAP_PX, y - SNAP_PX],
        [x + SNAP_PX, y + SNAP_PX],
      ],
      { layers: SNAP_LAYERS.filter((l) => this.map.getLayer(l)) },
    );
    let best: LngLat | undefined;
    let bestD = SNAP_PX * SNAP_PX;
    for (const hit of hits) {
      for (const c of corners(hit.geometry)) {
        const p = this.map.project(c);
        const d = (p.x - x) ** 2 + (p.y - y) ** 2;
        if (d < bestD) {
          bestD = d;
          best = c;
        }
      }
    }
    return best;
  };

  /** "Lot": click a lot and use its boundary as the shape. */
  private async pickLot(e: MapMouseEvent): Promise<void> {
    const lot = featuresAt(this.map, e.point).find((f) => f.kind === "parcel");
    const { patchDrawing } = useMapStore.getState();
    if (!lot) {
      patchDrawing({ error: "Click inside a lot." });
      return;
    }
    patchDrawing({ busy: true, error: null, check: null });
    const full = await featureDetail(lot.fid).catch(() => null);
    const geometry = full?.geometry ?? lot.geometry;
    this.setPreview(geometry, []);
    patchDrawing({
      busy: false,
      geometry,
      points: corners(geometry).length,
      complete: true,
    });
  }

  // ------------------------------------------------------------ lines

  private async addWaypoint(point: LngLat): Promise<void> {
    if (useMapStore.getState().drawing.complete) return;
    // The clicks of a double-click (to finish) land on the last waypoint; skip them.
    const last = this.waypoints.at(-1);
    if (last) {
      const [a, b] = [this.map.project(last), this.map.project(point)];
      if ((a.x - b.x) ** 2 + (a.y - b.y) ** 2 < SAME_SPOT_PX ** 2) return;
    }
    this.waypoints.push(point);
    await this.reroute();
  }

  private async reroute(): Promise<void> {
    const { patchDrawing } = useMapStore.getState();
    const points = [...this.waypoints];
    this.routeAbort?.abort();
    this.setPreview(null, points);
    if (points.length < 2) {
      patchDrawing({ geometry: null, points: points.length, streets: [], complete: false, check: null });
      return;
    }
    const abort = new AbortController();
    this.routeAbort = abort;
    patchDrawing({ busy: true, error: null, points: points.length, complete: false, check: null });
    try {
      const route = await routeLine(points, abort.signal);
      // Show the waypoints where the route actually turns: on the street.
      this.waypoints = route.waypoints;
      this.setPreview(route.geometry, route.waypoints);
      patchDrawing({ busy: false, geometry: route.geometry, streets: route.streets });
    } catch (err) {
      if (abort.signal.aborted) return;
      // Keep the last good route; drop the point that couldn't be reached.
      this.waypoints.pop();
      this.setPreview(useMapStore.getState().drawing.geometry, this.waypoints);
      patchDrawing({ busy: false, points: this.waypoints.length, error: (err as Error).message });
    }
  }

  // ------------------------------------------------------------ points

  /** Place a point, snapped onto the nearest street when one is close. */
  private placePoint(e: MapMouseEvent): void {
    const { x, y } = e.point;
    const streets = this.map.queryRenderedFeatures(
      [
        [x - STREET_SNAP_PX, y - STREET_SNAP_PX],
        [x + STREET_SNAP_PX, y + STREET_SNAP_PX],
      ],
      { layers: ["city-streets"] },
    );
    const click: LngLat = [e.lngLat.lng, e.lngLat.lat];
    let point = click;
    let bestD = Infinity;
    for (const s of streets) {
      if (s.geometry.type !== "LineString" && s.geometry.type !== "MultiLineString") continue;
      const snapped = nearestPointOnLine(s.geometry, click).geometry.coordinates as LngLat;
      const p = this.map.project(snapped);
      const d = (p.x - x) ** 2 + (p.y - y) ** 2;
      if (d < bestD && d <= STREET_SNAP_PX ** 2) {
        bestD = d;
        point = snapped;
      }
    }
    this.setPreview(null, [point]);
    useMapStore.getState().patchDrawing({
      geometry: { type: "Point", coordinates: point },
      points: 1,
      complete: true,
      check: null,
      error: null,
    });
  }
}

function corners(geometry: Geometry): LngLat[] {
  switch (geometry.type) {
    case "Polygon":
      return geometry.coordinates.flat() as LngLat[];
    case "MultiPolygon":
      return geometry.coordinates.flat(2) as LngLat[];
    default:
      return [];
  }
}
