<script lang="ts">
  import { deletePlace, patchPlace, type PlaceProps } from "./api";

  let { place, onchange, onclose }: { place: PlaceProps; onchange: () => void; onclose: () => void } = $props();

  let notes = $state("");
  let name = $state("");
  $effect(() => {
    notes = place.notes;
    name = place.name;
  });

  const isPool = $derived(place.category === "lap_pool");

  async function update(body: Parameters<typeof patchPlace>[1]) {
    await patchPlace(place.id, body);
    onchange();
  }

  async function remove() {
    await deletePlace(place.id);
    onclose();
    onchange();
  }
</script>

<section class="card">
  <header>
    <input class="name" bind:value={name} onchange={() => update({ name: name.trim() })} aria-label="Name" />
    <button class="x" onclick={onclose} aria-label="Close">×</button>
  </header>
  <div class="meta">
    {place.category_name}{place.address ? ` · ${place.address}` : ""}
    {#if place.source !== "manual"}· from {place.source === "park_district" ? "Chicago Park District" : "OpenStreetMap"}{/if}
  </div>
  {#if isPool}
    <div class="meta">
      Lap pool candidate: {place.lap_score ?? "unknown"} likelihood.{place.also ? ` Matches ${place.also}.` : ""}
    </div>
    <div class="row">
      <button class:on={place.state === "confirmed"} onclick={() => update({ state: "confirmed" })}>Confirm lap pool</button>
      <button class:on={place.state === "rejected"} onclick={() => update({ state: "rejected" })}>Not a lap pool</button>
      <button onclick={() => update({ state: "unreviewed" })}>Unreviewed</button>
    </div>
  {/if}
  <div class="row">
    <button class:on={place.favourite} onclick={() => update({ favourite: !place.favourite })}>
      {place.favourite ? "★ Favourite" : "☆ Favourite"}
    </button>
    <button onclick={remove}>{place.own ? "Delete" : "Hide"}</button>
  </div>
  <textarea bind:value={notes} onchange={() => update({ notes })} placeholder="Notes: length, lanes, hours, price…" rows="2"></textarea>
</section>

<style>
  .card { display: flex; flex-direction: column; gap: 6px; }
  header { display: flex; gap: 4px; }
  .name { flex: 1; font-weight: 600; font-size: 15px; }
  .x { background: none; border: 0; font-size: 20px; cursor: pointer; color: var(--muted); }
  .meta { color: var(--muted); font-size: 12px; }
  .row { display: flex; flex-wrap: wrap; gap: 4px; }
  button.on { background: var(--fg); color: var(--bg); }
  textarea { width: 100%; box-sizing: border-box; }
</style>
