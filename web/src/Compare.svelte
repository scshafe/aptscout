<script lang="ts">
  import type { Apartment } from "./api";

  let { apartments, onremove }: { apartments: Apartment[]; onremove: (id: number) => void } = $props();

  type Row = { label: string; get: (a: Apartment) => string | number | null; lower?: boolean };
  const rows: Row[] = [
    { label: "Rent", get: (a) => a.rent, lower: true },
    { label: "Fees", get: (a) => a.fees, lower: true },
    { label: "Beds", get: (a) => a.beds },
    { label: "Baths", get: (a) => a.baths },
    { label: "Sq ft", get: (a) => a.sqft },
    { label: "Floor", get: (a) => a.floor },
    { label: "Faces", get: (a) => a.facing.join(" ") || null },
    { label: "Place score", get: (a) => a.place_score ?? null },
    { label: "Status", get: (a) => a.status },
    { label: "Available", get: (a) => a.available_from },
    { label: "Pets", get: (a) => a.pets || null },
    { label: "Laundry", get: (a) => a.laundry || null },
    { label: "Parking", get: (a) => a.parking || null },
  ];

  /** True when the row's values differ across the apartments (so it is worth a look). */
  const differs = (r: Row) => new Set(apartments.map((a) => String(r.get(a)))).size > 1;
</script>

{#if apartments.length < 2}
  <p class="meta">Tick two to four apartments in the table to compare them side by side.</p>
{:else}
  <div class="scroll">
    <table>
      <thead>
        <tr>
          <th></th>
          {#each apartments as a (a.id)}
            <th>{a.label || a.address || "(no address)"}<button class="x" onclick={() => onremove(a.id)} aria-label="Remove">×</button></th>
          {/each}
        </tr>
      </thead>
      <tbody>
        {#each rows as r}
          <tr class:diff={differs(r)}>
            <th>{r.label}</th>
            {#each apartments as a (a.id)}<td>{r.get(a) ?? "–"}</td>{/each}
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}

<style>
  .meta { color: var(--muted); }
  .scroll { overflow-x: auto; }
  table { border-collapse: collapse; font-size: 13px; width: 100%; }
  th, td { padding: 4px 6px; border-bottom: 1px solid var(--line); text-align: left; }
  tr.diff td { background: color-mix(in srgb, #f5b301 18%, transparent); }
  .x { background: none; border: 0; cursor: pointer; color: var(--muted); }
</style>
