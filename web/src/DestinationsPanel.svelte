<script lang="ts">
  import { untrack } from "svelte";
  import {
    BANDS, BAND_LABEL, MODES, RULES, RULE_LABEL, addDestination, deleteDestination, geocode, patchDestination,
    type Category, type Destination,
  } from "./api";
  import type { WhatIf } from "./weeklyMath";

  let { destinations, categories, whatIf, pin, onwhatif, onpickpin, onchange, onedit }: {
    destinations: Destination[];
    categories: Category[];
    whatIf: WhatIf;
    pin?: { lat: number; lon: number };
    onwhatif: (id: number, trips: number | undefined) => void;
    onpickpin: () => void;
    onchange: () => void;
    onedit: (editing: boolean) => void;
  } = $props();

  let editing = $state<Destination | "new" | undefined>();
  const blank = (): Omit<Destination, "id"> => ({
    name: "", kind: "category", address: "", lat: null, lon: null, category_key: "grocery",
    selection_rule: "best", n: 3, trips_per_week: 1, mode: "walk", time_band: "weekday_midday",
    return_band: null, max_minutes: null,
  });
  let f = $state(blank());
  let candidates = $state<{ label: string; lat: number; lon: number }[]>([]);
  let message = $state("");

  function open(dest?: Destination) {
    const { id: _id, ...rest } = dest ?? ({ id: 0, ...blank() } as Destination);
    f = { ...rest };
    editing = dest ?? "new";
    candidates = [];
    message = "";
    onedit(true);
  }
  function close() {
    editing = undefined;
    onedit(false);
  }

  $effect(() => {
    const p = pin;
    if (p && untrack(() => editing)) {
      f.lat = p.lat;
      f.lon = p.lon;
    }
  });

  async function search() {
    message = "";
    try {
      candidates = await geocode(`${f.address} Chicago`);
      if (!candidates.length) message = "No match. Place the pin on the map.";
    } catch {
      message = "No geocoder available. Place the pin on the map.";
    }
  }

  async function save(e: SubmitEvent) {
    e.preventDefault();
    const body = { ...f, max_minutes: f.max_minutes === null || (f.max_minutes as unknown) === "" ? null : Number(f.max_minutes) };
    if (body.kind === "category") { body.lat = null; body.lon = null; } else { body.category_key = null; }
    try {
      if (editing && editing !== "new") await patchDestination(editing.id, body);
      else await addDestination(body);
      close();
      onchange();
    } catch (err) {
      message = "Could not save: " + (err instanceof Error ? err.message.slice(0, 160) : "error");
    }
  }

  async function remove(d: Destination) {
    await deleteDestination(d.id);
    onwhatif(d.id, undefined);
    onchange();
  }

  const catName = (key: string | null) => categories.find((c) => c.key === key)?.name ?? key ?? "";
  const weekTotal = $derived(destinations.reduce((t, d) => t + (whatIf[d.id] ?? d.trips_per_week), 0));
</script>

{#if editing}
  <form onsubmit={save}>
    <label>Name <input bind:value={f.name} required maxlength="80" placeholder="Job, groceries, gym…" /></label>
    <fieldset class="row">
      <label class="inline"><input type="radio" bind:group={f.kind} value="place" /> A specific place</label>
      <label class="inline"><input type="radio" bind:group={f.kind} value="category" /> A kind of place</label>
    </fieldset>
    {#if f.kind === "place"}
      <label>Address <input bind:value={f.address} placeholder="Street address" /></label>
      <div class="row">
        <button type="button" onclick={search} disabled={f.address.trim().length < 3}>Find on map</button>
        <button type="button" onclick={onpickpin}>Place pin on map</button>
        <span class="meta">{f.lat === null ? "no pin yet" : "pin set"}</span>
      </div>
      {#each candidates as c}
        <button type="button" class="cand" onclick={() => { f.lat = c.lat; f.lon = c.lon; candidates = []; }}>{c.label}</button>
      {/each}
    {:else}
      <label>Kind of place
        <select bind:value={f.category_key}>{#each categories as c (c.key)}<option value={c.key}>{c.name}</option>{/each}</select>
      </label>
      <label>Which one
        <select bind:value={f.selection_rule}>{#each RULES as r}<option value={r}>{RULE_LABEL[r]}</option>{/each}</select>
      </label>
      {#if f.selection_rule === "mean_n"}<label>N <input type="number" min="1" max="10" bind:value={f.n} /></label>{/if}
    {/if}
    <div class="grid">
      <label>Trips per week <input type="number" min="0" step="0.5" bind:value={f.trips_per_week} required /></label>
      <label>How
        <select bind:value={f.mode}>{#each MODES as m}<option value={m}>{m === "transit" ? "CTA transit" : m}</option>{/each}</select>
      </label>
      <label>When
        <select bind:value={f.time_band}>{#each BANDS as b}<option value={b}>{BAND_LABEL[b]}</option>{/each}</select>
      </label>
      <label>Return
        <select bind:value={f.return_band}>
          <option value={null}>same time</option>{#each BANDS as b}<option value={b}>{BAND_LABEL[b]}</option>{/each}
        </select>
      </label>
      <label>Longest each way (min) <input type="number" min="1" bind:value={f.max_minutes} placeholder="no limit" /></label>
    </div>
    {#if message}<p class="warn">{message}</p>{/if}
    <div class="row"><button>Save</button><button type="button" onclick={close}>Cancel</button></div>
  </form>
{:else}
  <div class="row"><button class="primary" onclick={() => open()}>+ Add destination</button>
    <span class="meta">{weekTotal} trips a week</span></div>
  {#if !destinations.length}
    <p class="meta">List where you go each week (job, groceries, gym…), how often, and how you travel. Apartments are then ranked by total weekly travel time.</p>
  {/if}
  <ul>
    {#each destinations as d (d.id)}
      <li>
        <div class="head">
          <strong>{d.name}</strong>
          <span class="meta">{d.kind === "category" ? catName(d.category_key) : "specific place"} · {d.mode === "transit" ? "CTA" : d.mode} · {BAND_LABEL[d.time_band].toLowerCase()}{d.max_minutes ? ` · max ${d.max_minutes} min` : ""}</span>
        </div>
        <div class="row">
          <label class="inline" title="Try a different number of trips without saving">
            <input type="range" min="0" max="14" step="0.5" value={whatIf[d.id] ?? d.trips_per_week}
              oninput={(e) => onwhatif(d.id, Number((e.currentTarget as HTMLInputElement).value))} />
            <span class:changed={whatIf[d.id] !== undefined && whatIf[d.id] !== d.trips_per_week}>{whatIf[d.id] ?? d.trips_per_week}×/wk</span>
          </label>
          {#if whatIf[d.id] !== undefined && whatIf[d.id] !== d.trips_per_week}
            <button onclick={async () => { await patchDestination(d.id, { trips_per_week: whatIf[d.id] }); onwhatif(d.id, undefined); onchange(); }}>Save</button>
            <button onclick={() => onwhatif(d.id, undefined)}>Reset</button>
          {/if}
          <button class="link" onclick={() => open(d)}>edit</button>
          <button class="link" onclick={() => remove(d)}>delete</button>
        </div>
      </li>
    {/each}
  </ul>
{/if}

<style>
  form { display: flex; flex-direction: column; gap: 8px; }
  label { display: flex; flex-direction: column; gap: 2px; font-size: 12px; color: var(--muted); }
  label.inline { flex-direction: row; align-items: center; gap: 6px; color: inherit; }
  input, select { font: inherit; padding: 6px; min-height: 32px; box-sizing: border-box; width: 100%; }
  input[type="radio"], input[type="range"] { width: auto; min-height: 0; padding: 0; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 6px; }
  .row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  fieldset { border: 0; padding: 0; margin: 0; }
  ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
  li { border-bottom: 1px solid var(--line); padding-bottom: 8px; }
  .head { display: flex; flex-direction: column; }
  .meta { color: var(--muted); font-size: 12px; }
  .changed { font-weight: 700; color: var(--warn); }
  .link { background: none; border: 0; color: var(--muted); text-decoration: underline; cursor: pointer; padding: 0; font: inherit; min-height: 0; }
  .cand { text-align: left; }
  .warn { color: var(--warn); margin: 0; }
</style>
