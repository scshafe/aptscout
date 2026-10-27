<script lang="ts">
  import { deleteApartment, type ApartmentDetail } from "./api";
  import { hoursMinutes } from "./weeklyMath";

  let { apt, onedit, ondeleted, onclose }: {
    apt: ApartmentDetail;
    onedit: () => void;
    ondeleted: () => void;
    onclose: () => void;
  } = $props();

  let confirming = $state(false);

  async function remove() {
    await deleteApartment(apt.id);
    ondeleted();
  }
</script>

<section>
  <header>
    <strong>{apt.label || apt.address || "(no address)"}{apt.unit ? ` #${apt.unit}` : ""}</strong>
    <button class="x" onclick={onclose} aria-label="Close">×</button>
  </header>
  <div class="facts">
    {apt.rent === null ? "" : `$${apt.rent}/mo`}
    {apt.beds ?? "?"} bd / {apt.baths ?? "?"} ba
    {apt.floor === null ? "" : `· floor ${apt.floor}${apt.floors_in_building ? " of " + apt.floors_in_building : ""}`}
    {apt.facing.length ? `· faces ${apt.facing.join("/")}` : ""}
  </div>
  {#if apt.listing_url}<a href={apt.listing_url} target="_blank" rel="noopener noreferrer">Listing</a>{/if}
  {#if apt.notes}<p class="notes">{apt.notes}</p>{/if}

  <h4>Weekly travel {hoursMinutes(apt.weekly.total)}</h4>
  {#if apt.lat === null}
    <p class="meta">Place the pin on the map to compute travel times.</p>
  {:else if !apt.weekly.destinations.length}
    <p class="meta">Add destinations in the Trips tab.</p>
  {:else}
    <table>
      <thead><tr><th>Destination</th><th>Via</th><th>Round trip</th><th>×/wk</th><th>Week</th></tr></thead>
      <tbody>
        {#each apt.weekly.destinations as d (d.id)}
          <tr class:over={d.over_budget}>
            <td>{d.name}{d.over_budget ? ` (over ${d.max_minutes} min)` : ""}</td>
            <td>{d.place?.name ?? d.note}{d.place && d.note ? ` (${d.note})` : ""} · {d.mode === "transit" ? "CTA" : d.mode}{d.method?.startsWith("estimate:fallback") ? " est. (schedule router down)" : d.method?.startsWith("estimate") ? " est." : d.method === "otp" ? " by schedule" : ""}</td>
            <td>{d.round_trip === null ? "–" : d.round_trip + "′"}</td>
            <td>{d.trips}</td>
            <td>{d.weekly === null ? "–" : hoursMinutes(d.weekly)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
    <div class="stack" aria-hidden="true">
      {#each apt.weekly.destinations as d, i (d.id)}
        {#if d.weekly}<span style:flex={d.weekly} style:opacity={1 - (i % 5) * 0.16} title="{d.name}: {hoursMinutes(d.weekly)}"></span>{/if}
      {/each}
    </div>
    <p class="meta">
      {#if apt.weekly.destinations.some((d) => d.method?.startsWith("estimate"))}Rows marked "est." come from straight-line distances, not the timetable. {/if}
      Transit uses the published schedule; delays are not modelled.
    </p>
  {/if}

  <h4>Place score {apt.score.place_score ?? "–"}</h4>
  {#if apt.lat === null}
    <p class="meta">Place the pin on the map to score this apartment.</p>
  {:else}
    <table>
      <thead><tr><th>Category</th><th>Counts</th><th>Walk</th><th>Pts</th><th>Share</th></tr></thead>
      <tbody>
        {#each apt.score.categories as c (c.key)}
          <tr>
            <td>{c.name}</td>
            <td>{c.place?.name ?? c.note}{c.place && c.note ? ` (${c.note})` : ""}</td>
            <td>{c.minutes === null ? "–" : c.minutes + "′"}</td>
            <td>{c.score}</td>
            <td title="weight {c.weight}">{c.contribution} of {c.share}</td>
          </tr>
        {/each}
      </tbody>
    </table>
    <p class="meta">Each category: 100 within its target walk, 0 beyond its maximum. Share is the weight's part of the total; the first number is the points it adds.</p>
  {/if}

  <details>
    <summary>Status history</summary>
    {#each apt.status_history as h}<div class="meta">{h.at.slice(0, 10)} {h.status}</div>{/each}
  </details>
  <div class="row">
    <button onclick={onedit}>Edit</button>
    {#if confirming}
      <button onclick={remove}>Really delete</button><button onclick={() => (confirming = false)}>Keep</button>
    {:else}
      <button onclick={() => (confirming = true)}>Delete</button>
    {/if}
  </div>
</section>

<style>
  section { display: flex; flex-direction: column; gap: 6px; }
  header { display: flex; justify-content: space-between; }
  .x { background: none; border: 0; font-size: 20px; cursor: pointer; color: var(--muted); }
  h4 { margin: 8px 0 0; }
  .meta { color: var(--muted); font-size: 12px; margin: 0; }
  .notes { margin: 0; white-space: pre-wrap; }
  table { border-collapse: collapse; font-size: 12px; width: 100%; }
  th, td { text-align: left; padding: 2px 4px; border-bottom: 1px solid var(--line); }
  .row { display: flex; gap: 6px; }
  tr.over td { color: var(--warn); }
  .stack { display: flex; height: 10px; border-radius: 5px; overflow: hidden; background: var(--line); }
  .stack span { background: var(--fg); border-right: 1px solid var(--bg); }
</style>
