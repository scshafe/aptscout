<script lang="ts">
  import { untrack } from "svelte";
  import { COMPASS, STATUSES, addApartment, geocode, patchApartment, type Apartment, type ApartmentInput, type Compass } from "./api";

  let { apartment, pin, onpickpin, onsaved, oncancel }: {
    apartment?: Apartment;
    pin?: { lat: number; lon: number };
    onpickpin: () => void;
    onsaved: (id: number) => void;
    oncancel: () => void;
  } = $props();

  // The form starts from the apartment as it was when opened; later changes do not overwrite typing.
  const a = untrack(() => apartment);
  const num = (v: number | null | undefined) => (v ?? "") as number | "";
  let f = $state({
    label: a?.label ?? "", address: a?.address ?? "", unit: a?.unit ?? "",
    rent: num(a?.rent), fees: num(a?.fees), deposit: num(a?.deposit),
    rent_includes: a?.rent_includes ?? "",
    beds: num(a?.beds), baths: num(a?.baths), sqft: num(a?.sqft),
    floor: num(a?.floor), floors_in_building: num(a?.floors_in_building),
    facing: [...(a?.facing ?? [])] as Compass[],
    lease_months: num(a?.lease_months), available_from: a?.available_from ?? "",
    pets: a?.pets ?? "", laundry: a?.laundry ?? "", parking: a?.parking ?? "",
    listing_url: a?.listing_url ?? "", status: a?.status ?? "interested",
    notes: a?.notes ?? "",
  });
  let coords = $state<{ lat: number | null; lon: number | null; source?: "geocoder" | "manual" }>({
    lat: a?.lat ?? null, lon: a?.lon ?? null,
  });
  let candidates = $state<{ label: string; lat: number; lon: number }[]>([]);
  let message = $state("");
  let advanced = $state(false);

  // A pin placed on the map (or dragged) replaces the coordinates.
  $effect(() => {
    if (pin) coords = { lat: pin.lat, lon: pin.lon, source: "manual" };
  });

  async function search() {
    message = "";
    candidates = [];
    try {
      candidates = await geocode(`${f.address} Chicago`);
      if (!candidates.length) message = "No match. Place the pin on the map.";
    } catch {
      message = "No geocoder available. Place the pin on the map.";
    }
  }

  function choose(c: { lat: number; lon: number }) {
    coords = { lat: c.lat, lon: c.lon, source: "geocoder" };
    candidates = [];
  }

  const toNum = (v: number | "") => (v === "" ? null : Number(v));

  async function save(e: SubmitEvent) {
    e.preventDefault();
    const body: ApartmentInput = {
      label: f.label, address: f.address, unit: f.unit, rent: toNum(f.rent), fees: toNum(f.fees),
      deposit: toNum(f.deposit), rent_includes: f.rent_includes, beds: toNum(f.beds), baths: toNum(f.baths),
      sqft: toNum(f.sqft), floor: toNum(f.floor), floors_in_building: toNum(f.floors_in_building),
      facing: f.facing, lease_months: toNum(f.lease_months), available_from: f.available_from || null,
      pets: f.pets, laundry: f.laundry, parking: f.parking, listing_url: f.listing_url, status: f.status,
      notes: f.notes, lat: coords.lat, lon: coords.lon,
    };
    if (coords.source) body.location_source = coords.source;
    try {
      if (apartment) {
        await patchApartment(apartment.id, body);
        onsaved(apartment.id);
      } else {
        onsaved((await addApartment(body)).id);
      }
    } catch (err) {
      message = "Could not save: " + (err instanceof Error ? err.message.slice(0, 160) : "error");
    }
  }

  function toggleFacing(c: Compass) {
    f.facing = f.facing.includes(c) ? f.facing.filter((x) => x !== c) : [...f.facing, c];
  }
</script>

<form onsubmit={save}>
  <label>Address <input bind:value={f.address} placeholder="Street address" /></label>
  <div class="row">
    <button type="button" onclick={search} disabled={f.address.trim().length < 3}>Find on map</button>
    <button type="button" onclick={onpickpin}>Place pin on map</button>
    <span class="meta">{coords.lat === null ? "no pin yet" : `pin set (${coords.source ?? apartment?.location_source ?? "manual"})`}</span>
  </div>
  {#each candidates as c}
    <button type="button" class="cand" onclick={() => choose(c)}>{c.label}</button>
  {/each}
  <div class="grid">
    <label>Rent $/mo <input type="number" min="0" bind:value={f.rent} inputmode="numeric" /></label>
    <label>Unit <input bind:value={f.unit} /></label>
    <label>Beds <input type="number" min="0" step="0.5" bind:value={f.beds} /></label>
    <label>Baths <input type="number" min="0" step="0.5" bind:value={f.baths} /></label>
    <label>Floor <input type="number" bind:value={f.floor} inputmode="numeric" /></label>
    <label>Floors in building <input type="number" min="1" bind:value={f.floors_in_building} /></label>
  </div>
  <fieldset>
    <legend>Facing</legend>
    <div class="compass">
      {#each COMPASS as c}
        <button type="button" class:on={f.facing.includes(c)} aria-pressed={f.facing.includes(c)} onclick={() => toggleFacing(c)}>{c}</button>
      {/each}
    </div>
  </fieldset>
  <label>Status
    <select bind:value={f.status}>{#each STATUSES as s}<option value={s}>{s}</option>{/each}</select>
  </label>
  <label>Notes <textarea bind:value={f.notes} rows="2"></textarea></label>
  <button type="button" class="link" onclick={() => (advanced = !advanced)}>{advanced ? "fewer fields" : "more fields"}</button>
  {#if advanced}
    <div class="grid">
      <label>Label <input bind:value={f.label} /></label>
      <label>Sq ft <input type="number" min="0" bind:value={f.sqft} /></label>
      <label>Fees $/mo <input type="number" min="0" bind:value={f.fees} /></label>
      <label>Deposit $ <input type="number" min="0" bind:value={f.deposit} /></label>
      <label>Rent includes <input bind:value={f.rent_includes} placeholder="heat, water…" /></label>
      <label>Lease (months) <input type="number" min="0" bind:value={f.lease_months} /></label>
      <label>Available <input type="date" bind:value={f.available_from} /></label>
      <label>Pets <input bind:value={f.pets} /></label>
      <label>Laundry <input bind:value={f.laundry} /></label>
      <label>Parking <input bind:value={f.parking} /></label>
    </div>
    <label>Listing link <input type="url" bind:value={f.listing_url} placeholder="https://" /></label>
  {/if}
  {#if message}<p class="warn">{message}</p>{/if}
  <div class="row"><button>{apartment ? "Save" : "Add apartment"}</button><button type="button" onclick={oncancel}>Cancel</button></div>
</form>

<style>
  form { display: flex; flex-direction: column; gap: 8px; }
  label { display: flex; flex-direction: column; gap: 2px; font-size: 12px; color: var(--muted); }
  input, select, textarea { font: inherit; padding: 6px; min-height: 32px; box-sizing: border-box; width: 100%; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 6px; }
  .row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .meta { color: var(--muted); font-size: 12px; }
  .cand { text-align: left; }
  fieldset { border: 1px solid var(--line); border-radius: 6px; }
  .compass { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; }
  .compass button { min-height: 40px; }
  button.on { background: var(--fg); color: var(--bg); }
  .link { background: none; border: 0; color: var(--muted); text-decoration: underline; cursor: pointer; align-self: flex-start; padding: 0; }
  .warn { color: var(--warn); margin: 0; }
  button { min-height: 32px; }
</style>
