/** Design tokens the map needs, read from the CSS variables in globals.css. */
export type MapTokens = {
  ground: string;
  road: string;
  building: string;
  buildingSelected: string;
  water: string;
  park: string;
  label: string;
  removed: string;
  proposalPark: string;
  accent: string;
  bg: string;
};

const cssVars: Record<keyof MapTokens, string> = {
  ground: "--color-map-ground",
  road: "--color-map-road",
  building: "--color-map-building",
  buildingSelected: "--color-map-building-selected",
  water: "--color-map-water",
  park: "--color-map-park",
  label: "--color-map-label",
  removed: "--color-map-removed",
  proposalPark: "--color-map-proposal-park",
  accent: "--color-accent",
  bg: "--color-bg",
};

export function readMapTokens(): MapTokens {
  const style = getComputedStyle(document.documentElement);
  return Object.fromEntries(
    Object.entries(cssVars).map(([key, name]) => [key, style.getPropertyValue(name).trim()]),
  ) as MapTokens;
}
