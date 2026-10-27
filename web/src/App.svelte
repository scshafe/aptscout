<script lang="ts">
  import { onMount } from "svelte";
  import * as maplibregl from "maplibre-gl";
  import type { GeoJSONSourceSpecification } from "maplibre-gl";
  import { Protocol } from "pmtiles";
  import {
    getApartment, getApartments, getCategories, getConfig, getDatasets, getDestinations, getPlaces, getSettings, putSettings,
    type Apartment, type ApartmentDetail, type Category, type Dataset, type Destination, type MapConfig, type PlaceCollection, type Settings,
  } from "./api";
  import { basemapStyle } from "./mapStyle";
  import CategoryPanel from "./CategoryPanel.svelte";
  import PlaceCard from "./PlaceCard.svelte";
  import AddPlace from "./AddPlace.svelte";
  import ApartmentTable from "./ApartmentTable.svelte";
  import ApartmentForm from "./ApartmentForm.svelte";
  import ApartmentDetailView from "./ApartmentDetail.svelte";
  import Compare from "./Compare.svelte";
  import DestinationsPanel from "./DestinationsPanel.svelte";
  import type { WhatIf } from "./weeklyMath";
  import { discard, flush, load as loadQueue, type Queued } from "./offline";
  import { addApartment } from "./api";

  type GeoData = GeoJSONSourceSpecification["data"];
  const STATUS_COLOUR: Record<string, string> = {
    interested: "#1f78d1", contacted: "#8a56c2", toured: "#e08a00", applied: "#d9531e", rejected: "#888888", signed: "#1b8a3a",
  };

  let container: HTMLDivElement;
  let map: maplibregl.Map | undefined;
  let marker: maplibregl.Marker | undefined;
  let config = $state<MapConfig>();
  let datasets = $state<Record<string, Dataset>>({});
  let error = $state("");
  let show = $state({ rail: true, bus: false, stops: true });
  let tab = $state<"apartments" | "trips" | "places" | "compare">("apartments");

  let categories = $state<Category[]>([]);
  let places = $state<PlaceCollection>({ type: "FeatureCollection", features: [] });
  let apartments = $state<Apartment[]>([]);
  let destinations = $state<Destination[]>([]);
  let settings = $state<Settings>({ combined_on: false, w_place: 5, w_time: 8, w_rent: 3 });
  let whatIf = $state<WhatIf>({});
  let editingDest = $state(false);
  let queued = $state<Queued[]>(loadQueue());
  let online = $state(typeof navigator === "undefined" ? true : navigator.onLine);
  let selectedPlaceId = $state<number>();
  let selectedAptId = $state<number>();
  let detail = $state<ApartmentDetail>();
  let compare = $state<number[]>([]);
  let mode = $state<"none" | "place" | "pin">("none");
  let pendingPlace = $state<{ lng: number; lat: number }>();
  let form = $state<{ apartment?: Apartment } | undefined>();
  let formPin = $state<{ lat: number; lon: number }>();

  const cta = $derived(datasets.cta_gtfs);
  const selectedPlace = $derived(places.features.find((f) => f.properties.id === selectedPlaceId)?.properties);
  const compared = $derived(compare.map((id) => apartments.find((a) => a.id === id)).filter((a): a is Apartment => !!a));
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

  function aptFeatures(): GeoData {
    return {
      type: "FeatureCollection",
      features: apartments.filter((a) => a.lat !== null && a.lon !== null).map((a) => ({
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [a.lon!, a.lat!] },
        properties: { id: a.id, rent: a.rent === null ? "" : "$" + a.rent, colour: STATUS_COLOUR[a.status] ?? "#1f78d1", selected: a.id === selectedAptId },
      })),
    };
  }

  function linkFeatures(): GeoData {
    const apt = detail;
    return {
      type: "FeatureCollection",
      features: apt && apt.lat !== null
        ? apt.score.categories.filter((c) => c.place).map((c) => ({
            type: "Feature" as const,
            geometry: { type: "LineString" as const, coordinates: [[apt.lon!, apt.lat!], [c.place!.lon, c.place!.lat]] },
            properties: { name: c.name },
          }))
        : [],
    };
  }

  function syncMap() {
    (map?.getSource("places") as maplibregl.GeoJSONSource | undefined)?.setData(places as GeoData);
    if (map?.getLayer("places")) map.setFilter("places", placeFilter());
    (map?.getSource("apartments") as maplibregl.GeoJSONSource | undefined)?.setData(aptFeatures());
    (map?.getSource("links") as maplibregl.GeoJSONSource | undefined)?.setData(linkFeatures());
  }

  async function refresh() {
    [categories, places, apartments, destinations] = await Promise.all([getCategories(), getPlaces(), getApartments(), getDestinations()]);
    if (selectedAptId !== undefined) await loadDetail(selectedAptId);
    syncMap();
  }

  async function loadDetail(id: number) {
    try {
      detail = await getApartment(id);
    } catch {
      detail = undefined;
      selectedAptId = undefined;
    }
  }

  async function selectApartment(id: number) {
    selectedAptId = id;
    form = undefined;
    await loadDetail(id);
    syncMap();
    const a = apartments.find((x) => x.id === id);
    if (a?.lat != null && a.lon != null) map?.easeTo({ center: [a.lon, a.lat], duration: 400 });
  }

  function closeApartment() {
    selectedAptId = undefined;
    detail = undefined;
    syncMap();
  }

  async function sync() {
    if (!queued.length) return;
    const result = await flush(addApartment);
    queued = result.remaining;
    if (result.sent) await refresh();
  }

  function setWhatIf(id: number, trips: number | undefined) {
    if (trips === undefined) {
      const { [id]: _drop, ...rest } = whatIf;
      whatIf = rest;
    } else {
      whatIf = { ...whatIf, [id]: trips };
    }
  }

  async function changeSettings(change: Partial<Settings>) {
    settings = { ...settings, ...change };
    settings = await putSettings(change);
  }

  function toggleCompare(id: number) {
    compare = compare.includes(id) ? compare.filter((x) => x !== id) : [...compare, id].slice(-4);
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

  // The draggable pin is shown while the form is open with a location.
  $effect(() => {
    const at = formPin ?? (form?.apartment?.lat != null ? { lat: form.apartment.lat, lon: form.apartment.lon! } : undefined);
    if (!map || !(form || editingDest) || !at) {
      marker?.remove();
      marker = undefined;
      return;
    }
    if (!marker) {
      marker = new maplibregl.Marker({ draggable: true, color: "#d9531e" }).setLngLat([at.lon, at.lat]).addTo(map);
      marker.on("dragend", () => {
        const p = marker!.getLngLat();
        formPin = { lat: p.lat, lon: p.lng };
      });
    } else {
      marker.setLngLat([at.lon, at.lat]);
    }
  });

  onMount(() => {
    const goOnline = () => { online = true; sync(); };
    const goOffline = () => (online = false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    sync();
    const protocol = new Protocol();
    maplibregl.addProtocol("pmtiles", protocol.tile);
    (async () => {
      try {
        config = await getConfig();
        datasets = await getDatasets();
        [categories, places, apartments, destinations, settings] = await Promise.all([
          getCategories(), getPlaces(), getApartments(), getDestinations(), getSettings()]);
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
        addApartments(map!);
      });
      map.on("click", (e) => {
        if (mode === "place") {
          pendingPlace = { lng: e.lngLat.lng, lat: e.lngLat.lat };
        } else if (mode === "pin") {
          formPin = { lat: e.lngLat.lat, lon: e.lngLat.lng };
        }
        mode = "none";
      });
    })();
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
      marker?.remove();
      map?.remove();
      maplibregl.removeProtocol("pmtiles");
    };
  });

  function addApartments(m: maplibregl.Map) {
    m.addSource("links", { type: "geojson", data: linkFeatures() });
    m.addLayer({ id: "links", type: "line", source: "links", paint: { "line-color": "#333", "line-width": 1.5, "line-dasharray": [2, 2] } });
    m.addSource("apartments", { type: "geojson", data: aptFeatures() });
    m.addLayer({
      id: "apartments", type: "circle", source: "apartments",
      paint: {
        "circle-radius": ["case", ["get", "selected"], 11, 8],
        "circle-color": ["get", "colour"],
        "circle-stroke-color": "#fff", "circle-stroke-width": 2,
      },
    });
    if (config?.tiles) {
      m.addLayer({
        id: "apartment-rent", type: "symbol", source: "apartments",
        layout: { "text-field": ["get", "rent"], "text-font": ["Noto Sans Medium"], "text-size": 12, "text-offset": [0, -1.6], "text-allow-overlap": true },
        paint: { "text-color": "#111", "text-halo-color": "#fff", "text-halo-width": 2 },
      });
    }
    m.on("click", "apartments", (e) => {
      const f = e.features?.[0];
      if (f && mode === "none") {
        tab = "apartments";
        selectApartment(Number(f.properties?.id));
      }
    });
    m.on("mouseenter", "apartments", () => (m.getCanvas().style.cursor = "pointer"));
    m.on("mouseleave", "apartments", () => (m.getCanvas().style.cursor = ""));
  }

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
      if (mode !== "none") return;
      const f = e.features?.[0];
      if (f) {
        tab = "places";
        selectedPlaceId = Number(f.properties?.id);
      }
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
    for (const layer of ["cta-rail-stops", "cta-bus-stops"]) {
      m.on("click", layer, (e) => {
        const f = e.features?.[0];
        if (f && mode === "none") new maplibregl.Popup().setLngLat(e.lngLat).setText(String(f.properties?.name)).addTo(m);
      });
    }
  }

  function openForm(apartment?: Apartment) {
    formPin = undefined;
    form = { apartment };
    tab = "apartments";
  }

  async function saved(id: number) {
    form = undefined;
    formPin = undefined;
    await refresh();
    await selectApartment(id);
  }
</script>

<div class="app">
  <div class="map" bind:this={container}></div>
  <button class="fab" onclick={() => openForm()} aria-label="Add apartment">+</button>
  {#if mode !== "none"}<div class="hint">{mode === "pin" ? "Click the map to place the pin" : "Click the map to place the new place"}</div>{/if}

  <aside class="side">
    <header>
      <strong>{config?.city ?? "aptscout"}</strong>
      <nav>
        <button class:on={tab === "apartments"} onclick={() => (tab = "apartments")}>Apartments</button>
        <button class:on={tab === "trips"} onclick={() => (tab = "trips")}>Trips{destinations.length ? ` (${destinations.length})` : ""}</button>
        <button class:on={tab === "compare"} onclick={() => (tab = "compare")}>Compare{compare.length ? ` (${compare.length})` : ""}</button>
        <button class:on={tab === "places"} onclick={() => (tab = "places")}>Places</button>
      </nav>
    </header>
    {#if error}<p class="warn">{error}</p>{/if}
    {#if !online}<p class="warn">Offline: showing the last data. New apartments are kept on this device.</p>{/if}
    {#if queued.length}
      <section class="queue">
        <strong>Waiting to sync ({queued.length})</strong>
        {#each queued as q (q.id)}
          <div class="qrow">
            <span>{q.body.address || "(no address)"}{q.body.rent ? ` · $${q.body.rent}` : ""}{q.error ? ` — ${q.error}` : ""}</span>
            <button onclick={() => (queued = discard(q.id))}>Discard</button>
          </div>
        {/each}
        {#if online}<button onclick={sync}>Try now</button>{/if}
      </section>
    {/if}

    {#if tab === "apartments"}
      {#if form}
        <ApartmentForm
          apartment={form.apartment} pin={formPin}
          onpickpin={() => (mode = "pin")} onsaved={saved}
          onqueued={() => { queued = loadQueue(); form = undefined; formPin = undefined; }} oncancel={() => { form = undefined; formPin = undefined; }}
        />
      {:else if detail}
        <ApartmentDetailView apt={detail} onclose={closeApartment} onedit={() => openForm(apartments.find((a) => a.id === detail!.id))}
          ondeleted={() => { closeApartment(); refresh(); }} />
      {:else}
        <button class="primary" onclick={() => openForm()}>+ Add apartment</button>
      {/if}
      {#if !form}
        <ApartmentTable {apartments} {categories} {settings} {whatIf} onsettings={changeSettings} selectedId={selectedAptId} {compare} onselect={selectApartment} oncompare={toggleCompare} />
      {/if}
    {:else if tab === "trips"}
      <DestinationsPanel {destinations} {categories} {whatIf} pin={formPin} onwhatif={setWhatIf}
        onpickpin={() => (mode = "pin")} onchange={refresh}
        onedit={(on) => { editingDest = on; if (!on) formPin = undefined; }} />
    {:else if tab === "compare"}
      <Compare apartments={compared} onremove={toggleCompare} />
    {:else}
      <div class="layers">
        <label><input type="checkbox" bind:checked={show.rail} /> CTA rail lines</label>
        <label><input type="checkbox" bind:checked={show.bus} /> CTA bus routes</label>
        <label><input type="checkbox" bind:checked={show.stops} /> Stops</label>
      </div>
      <CategoryPanel {categories} {counts} onchange={refresh} />
      <button onclick={() => (mode = mode === "place" ? "none" : "place")}>{mode === "place" ? "Click the map…" : "+ Add place"}</button>
      {#if pendingPlace}
        <AddPlace {categories} at={pendingPlace} oncancel={() => (pendingPlace = undefined)}
          oncreated={() => { pendingPlace = undefined; refresh(); }} />
      {/if}
      {#if selectedPlace}
        <PlaceCard place={selectedPlace} onchange={refresh} onclose={() => (selectedPlaceId = undefined)} />
      {/if}
      {#if config && !config.tiles}
        <p class="warn">No basemap tiles yet. Run <code>python -m aptscout build-tiles</code>.</p>
      {/if}
    {/if}
  </aside>

  <footer class="foot">
    {#if datasets.otp_inputs && datasets.otp_inputs.status !== "ok"}
      <span class="warn">Transit routing graph is {datasets.otp_inputs.status}.</span>
    {/if}
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
</div>

<style>
  .app {
    position: fixed; inset: 0; display: grid; grid-template-columns: minmax(0, 1fr) minmax(360px, 480px);
    grid-template-rows: minmax(0, 1fr) auto; grid-template-areas: "map side" "foot foot";
  }
  .map { grid-area: map; position: relative; }
  .side {
    grid-area: side; overflow-y: auto; padding: 8px 12px; background: var(--bg); border-left: 1px solid var(--line);
    display: flex; flex-direction: column; gap: 8px;
  }
  .foot {
    grid-area: foot; padding: 4px 8px calc(env(safe-area-inset-bottom, 0px) + 4px);
    background: var(--panel); border-top: 1px solid var(--line); font-size: 11px; color: var(--muted);
  }
  header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px; }
  nav { display: flex; gap: 4px; }
  nav button.on { background: var(--fg); color: var(--bg); }
  .primary { align-self: flex-start; }
  .queue { border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; display: flex; flex-direction: column; gap: 4px; }
  .qrow { display: flex; justify-content: space-between; gap: 6px; font-size: 12px; }
  .fab { display: none; }
  .layers { display: flex; flex-direction: column; gap: 2px; }
  .hint {
    position: absolute; left: 12px; top: calc(env(safe-area-inset-top, 0px) + 12px); z-index: 2;
    background: var(--panel); border: 1px solid var(--line); padding: 6px 10px; border-radius: 6px;
  }
  .warn { color: var(--warn); margin: 0; }
  label { display: flex; gap: 6px; align-items: center; }
  :global(button) { min-height: 32px; }
  @media (max-width: 760px) {
    .app { grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(0, 45vh) minmax(0, 1fr) auto; grid-template-areas: "map" "side" "foot"; }
    .side { border-left: 0; border-top: 1px solid var(--line); }
    .fab {
      display: block; position: fixed; right: 16px; bottom: calc(env(safe-area-inset-bottom, 0px) + 44px); z-index: 5;
      width: 52px; height: 52px; border-radius: 50%; border: 0; font-size: 28px; background: #d9531e; color: #fff;
      box-shadow: 0 2px 8px #0006;
    }
  }
</style>
