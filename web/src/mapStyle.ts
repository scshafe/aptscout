import { layers, namedFlavor } from "@protomaps/basemaps";
import type { StyleSpecification } from "maplibre-gl";

/** The basemap style: Protomaps layers over the self-hosted PMTiles file. */
export function basemapStyle(hasTiles: boolean): StyleSpecification {
  const background = { id: "background", type: "background" as const, paint: { "background-color": "#f4f1ea" } };
  if (!hasTiles) {
    return { version: 8, sources: {}, layers: [background] };
  }
  return {
    version: 8,
    glyphs: "/basemap-assets/fonts/{fontstack}/{range}.pbf",
    sprite: `${location.origin}/basemap-assets/sprites/v4/light`,
    sources: {
      basemap: {
        type: "vector",
        url: `pmtiles://${location.origin}/tiles/city.pmtiles`,
        attribution: "© OpenStreetMap contributors · Protomaps",
      },
    },
    layers: layers("basemap", namedFlavor("light"), { lang: "en" }),
  };
}
