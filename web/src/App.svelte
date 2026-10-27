<script lang="ts">
  import { onMount } from "svelte";
  import * as maplibregl from "maplibre-gl";
  import type { GeoJSONSourceSpecification } from "maplibre-gl";
  import { Protocol } from "pmtiles";
  import { getCategories, getConfig, getDatasets, getPlaces, type Category, type Dataset, type MapConfig, type PlaceCollection, type PlaceProps } from "./api";
  import CategoryPanel from "./CategoryPanel.svelte";
  import PlaceCard from "./PlaceCard.svelte";
  import AddPlace from "./AddPlace.svelte";
  import { basemapStyle } from "./mapStyle";

  type GeoData = GeoJSONSourceSpecification["data"];
  let container: HTMLDivElement;
  let map: maplibregl.Map | undefined;
  let config = $state<MapConfig>();
  let datasets = $state<Record<string, Dataset>>({});
  let error = $state("");
  let show = $state({ rail: true, bus: false, stops: true });

  let categories = $state<Category[]>([]);
  let places = $state<PlaceCollection>({ type: "FeatureCollection", features: [] });
  let selectedId = $state<number>();
  let placing = $state(false);
  let pending = $state<{ lng: number; lat: number }>();

  const cta = $derived(datasets.cta_gtfs);
  const selected = $derived(places.features.find((f) => f.properties.id === selectedId)?.properties);
  const counts = $derived.by(() => {
    const out: Record<string, number> = {};
    for (const f of places.features) {
      const p = f.properties;
      if (p.category === "lap_pool" && !(p.state === "confirmed" || (p.state === "unreviewed" && p.lap_score !== "unlikely"))) continue;
      out[p.category] = (out[p.category] ?? 0) + 1;
    }
    return out;
  });

  /** Which places the map draws: visible categories; unreviewed lap pools only when plausible. */
  function placeFilter(): maplibregl.FilterSpecification {
    const visible = categories.filter((c) => c.visible && !c.transit).map((c) => c.key);
    return [
      "all",
      ["in", ["get", "category"], ["literal", visible]],
      ["any",
        ["!=", ["get", "category"], "lap_pool"],
        ["==", ["get", "state"], "confirmed"],
        ["all", ["==", ["get", "state"], "unreviewed"], ["!=", ["get", "lap_score"], "unlikely"]]],
    ];
  }

  async function refresh() {
    [categories, places] = await Promise.all([getCategories(), getPlaces()]);
    (map?.getSource("places") as maplibregl.GeoJSONSource | undefined)?.setData(places as GeoData);
    if (map?.getLayer("places")) map.setFilter("places", placeFilter());
  }

  function setVisible(layer: string, on: boolean) {
    if (map?.getLayer(layer)) map.setLayoutProperty(layer, "visibility", on ? "visible" : "none");
  }
  $effect(() => {
    setVisible("cta-rail", show.rail);
    setVisible("cta-bus", show.bus);
    setVisible("cta-rail-stops", show.stops);
    setVisible("cta-bus-stops", show.stops && show.bus);
  });

  onMount(() => {
    const protocol = new Protocol();
    maplibregl.addProtocol("pmtiles", protocol.tile);
    (async () => {
      try {
        config = await getConfig();
        datasets = await getDatasets();
        categories = await getCategories();
        places = await getPlaces();
      } catch (e) {
        error = "Could not load the map settings. Are you signed in?";
        return;
      }
      map = new maplibregl.Map({
        container,
        style: basemapStyle(config.tiles),
        center: config.center,
        zoom: config.zoom,
        attributionControl: { compact: true },
      });
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
      map.addControl(new maplibregl.GeolocateControl({ trackUserLocation: false }), "top-right");
      map.on("load", () => {
        addCta(map!);
        addPlaces(map!);
      });
      map.on("click", (e) => {
        if (placing) {
          pending = { lng: e.lngLat.lng, lat: e.lngLat.lat };
          placing = false;
        }
      });
    })();
    return () => {
      map?.remove();
      maplibregl.removeProtocol("pmtiles");
    };
  });

  function addPlaces(m: maplibregl.Map) {
    m.addSource("places", { type: "geojson", data: places as GeoData });
    m.addLayer({
      id: "places", type: "circle", source: "places", filter: placeFilter(),
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 3, 16, 8],
        "circle-color": ["get", "colour"],
        "circle-opacity": ["case", ["==", ["get", "state"], "unreviewed"], ["case", ["==", ["get", "category"], "lap_pool"], 0.45, 0.9], 0.95],
        "circle-stroke-color": ["case", ["get", "favourite"], "#f5b301", "#ffffff"],
        "circle-stroke-width": ["case", ["get", "favourite"], 3, 1],
      },
    });
    m.on("click", "places", (e) => {
      if (placing) return;
      const f = e.features?.[0];
      if (f) selectedId = Number(f.properties?.id);
    });
    m.on("mouseenter", "places", () => (m.getCanvas().style.cursor = "pointer"));
    m.on("mouseleave", "places", () => (m.getCanvas().style.cursor = ""));
  }

  function addCta(m: maplibregl.Map) {
    for (const name of ["rail", "bus", "stops"]) {
      m.addSource(`cta-${name}`, { type: "geojson", data: `/api/cta/${name}` });
    }
    m.addLayer({
      id: "cta-bus", type: "line", source: "cta-bus",
      layout: { visibility: "none", "line-cap": "round" },
      paint: { "line-color": ["get", "color"], "line-width": 1.5, "line-opacity": 0.7 },
    });
    m.addLayer({
      id: "cta-rail", type: "line", source: "cta-rail",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": ["get", "color"], "line-width": ["interpolate", ["linear"], ["zoom"], 9, 2, 15, 6] },
    });
    m.addLayer({
      id: "cta-bus-stops", type: "circle", source: "cta-stops", minzoom: 14,
      filter: ["==", ["get", "kind"], "bus"], layout: { visibility: "none" },
      paint: { "circle-radius": 3, "circle-color": "#fff", "circle-stroke-color": "#444", "circle-stroke-width": 1 },
    });
    m.addLayer({
      id: "cta-rail-stops", type: "circle", source: "cta-stops", minzoom: 11,
      filter: ["==", ["get", "kind"], "rail"],
      paint: { "circle-radius": 4, "circle-color": "#fff", "circle-stroke-color": "#222", "circle-stroke-width": 2 },
    });
    m.on("click", "cta-rail-stops", (e) => {
      const f = e.features?.[0];
      if (f) new maplibregl.Popup().setLngLat(e.lngLat).setText(String(f.properties?.name)).addTo(m);
    });
    m.on("click", "cta-bus-stops", (e) => {
      const f = e.features?.[0];
      if (f) new maplibregl.Popup().setLngLat(e.lngLat).setText(String(f.properties?.name)).addTo(m);
    });
  }
</script>

<div class="map" bind:this={container}></div>

<aside class="panel">
  <strong>{config?.city ?? "aptscout"}</strong>
  <label><input type="checkbox" bind:checked={show.rail} /> CTA rail lines</label>
  <label><input type="checkbox" bind:checked={show.bus} /> CTA bus routes</label>
  <label><input type="checkbox" bind:checked={show.stops} /> Stops</label>
  <CategoryPanel {categories} {counts} onchange={refresh} />
  <button onclick={() => (placing = !placing)}>{placing ? "Click the map…" : "+ Add place"}</button>
  {#if pending}
    <AddPlace {categories} at={pending} oncancel={() => (pending = undefined)}
      oncreated={() => { pending = undefined; refresh(); }} />
  {/if}
  {#if selected}
    <PlaceCard place={selected} onchange={refresh} onclose={() => (selectedId = undefined)} />
  {/if}
  {#if error}<p class="warn">{error}</p>{/if}
  {#if config && !config.tiles}
    <p class="warn">No basemap tiles yet. Run <code>python -m aptscout build-tiles</code>.</p>
  {/if}
</aside>

<footer class="foot">
  {#if cta?.status === "expired"}
    <span class="warn">CTA schedule data expired {cta.valid_to}.</span>
  {:else if cta?.status === "expiring"}
    <span class="warn">CTA schedule data ends {cta.valid_to}.</span>
  {:else if cta?.valid_to}
    CTA schedule valid to {cta.valid_to}.
  {:else}
    CTA data not imported.
  {/if}
  Data provided by Chicago Transit Authority (scheduled service, not guaranteed accurate; aptscout is not
  affiliated with the CTA). Map data © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>.
</footer>

<style>
  .map { position: fixed; inset: 0; }
  .panel {
    position: fixed; top: calc(env(safe-area-inset-top, 0px) + 8px); left: 8px;
    background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
    padding: 8px 12px; display: flex; flex-direction: column; gap: 6px; width: min(300px, calc(100vw - 80px));
    max-height: calc(100vh - 80px); overflow-y: auto;
  }
  .foot {
    position: fixed; left: 0; right: 0; bottom: 0; padding: 4px 8px calc(env(safe-area-inset-bottom, 0px) + 4px);
    background: var(--panel); border-top: 1px solid var(--line); font-size: 11px; color: var(--muted);
  }
  .warn { color: var(--warn); margin: 0; }
  label { display: flex; gap: 6px; align-items: center; }
</style>
