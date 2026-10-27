<script lang="ts">
  import { COMPASS, STATUSES, type Apartment, type Category } from "./api";

  let { apartments, categories, selectedId, compare, onselect, oncompare }: {
    apartments: Apartment[];
    categories: Category[];
    selectedId?: number;
    compare: number[];
    onselect: (id: number) => void;
    oncompare: (id: number) => void;
  } = $props();

  type SortKey = "rent" | "place_score" | "floor" | "beds" | string;
  let sortKey = $state<SortKey>("place_score");
  let sortDir = $state<1 | -1>(-1);
  let statusFilter = $state<string[]>(["interested", "contacted", "toured", "applied"]);
  let maxRent = $state<number | "">("");
  let minBeds = $state<number | "">("");
  let facing = $state("");
  let shownCats = $state<string[]>(["grocery", "rail_station"]);

  const value = (a: Apartment, key: SortKey): number | null =>
    key.startsWith("min:") ? (a.minutes?.[key.slice(4)] ?? null) : ((a as unknown as Record<string, number | null>)[key] ?? null);

  const rows = $derived.by(() => {
    const out = apartments.filter((a) =>
      statusFilter.includes(a.status) &&
      (maxRent === "" || (a.rent ?? 0) <= maxRent) &&
      (minBeds === "" || (a.beds ?? 0) >= minBeds) &&
      (facing === "" || a.facing.includes(facing as never)));
    out.sort((a, b) => {
      const x = value(a, sortKey), y = value(b, sortKey);
      if (x === null && y === null) return 0;
      if (x === null) return 1;  // empty values sort last in either direction
      if (y === null) return -1;
      return (x - y) * sortDir;
    });
    return out;
  });

  /** The best value in a column (lowest for money and minutes, highest for the score). */
  function best(key: SortKey): number | null {
    const vals = rows.map((a) => value(a, key)).filter((v): v is number => v !== null);
    if (!vals.length) return null;
    return key === "place_score" ? Math.max(...vals) : Math.min(...vals);
  }
  const bests = $derived({ rent: best("rent"), place_score: best("place_score") });

  function sortBy(key: SortKey) {
    if (sortKey === key) sortDir = (sortDir * -1) as 1 | -1;
    else { sortKey = key; sortDir = key === "place_score" ? -1 : 1; }
  }
  const arrow = (key: SortKey) => (sortKey === key ? (sortDir === 1 ? " ▲" : " ▼") : "");
  const scored = $derived(categories.filter((c) => c.weight > 0));
  function toggleCat(key: string) {
    shownCats = shownCats.includes(key) ? shownCats.filter((k) => k !== key) : [...shownCats, key];
  }
  function toggleStatus(s: string) {
    statusFilter = statusFilter.includes(s) ? statusFilter.filter((k) => k !== s) : [...statusFilter, s];
  }
</script>

<div class="filters">
  <div class="chips">
    {#each STATUSES as s}
      <button class:on={statusFilter.includes(s)} aria-pressed={statusFilter.includes(s)} onclick={() => toggleStatus(s)}>{s}</button>
    {/each}
  </div>
  <label>Max rent <input type="number" min="0" bind:value={maxRent} /></label>
  <label>Min beds <input type="number" min="0" step="0.5" bind:value={minBeds} /></label>
  <label>Facing
    <select bind:value={facing}><option value="">any</option>{#each COMPASS as c}<option>{c}</option>{/each}</select>
  </label>
  <details>
    <summary>Distance columns</summary>
    {#each scored as c (c.key)}
      <label class="inline"><input type="checkbox" checked={shownCats.includes(c.key)} onchange={() => toggleCat(c.key)} /> {c.name}</label>
    {/each}
  </details>
</div>

<div class="scroll">
  <table>
    <thead>
      <tr>
        <th></th>
        <th>Apartment</th>
        <th><button onclick={() => sortBy("rent")}>Rent{arrow("rent")}</button></th>
        <th><button onclick={() => sortBy("beds")}>Bd/ba{arrow("beds")}</button></th>
        <th><button onclick={() => sortBy("floor")}>Fl{arrow("floor")}</button></th>
        <th>Faces</th>
        <th><button onclick={() => sortBy("place_score")}>Score{arrow("place_score")}</button></th>
        {#each scored.filter((c) => shownCats.includes(c.key)) as c (c.key)}
          <th><button onclick={() => sortBy("min:" + c.key)} title={c.name + ", walking minutes"}>{c.name.replace("CTA ", "")}{arrow("min:" + c.key)}</button></th>
        {/each}
      </tr>
    </thead>
    <tbody>
      {#each rows as a (a.id)}
        <tr class:sel={a.id === selectedId} onclick={() => onselect(a.id)}>
          <td onclick={(e) => e.stopPropagation()}>
            <input type="checkbox" checked={compare.includes(a.id)} onchange={() => oncompare(a.id)} aria-label="Compare" />
          </td>
          <td class="name">{a.label || a.address || "(no address)"}{a.unit ? ` #${a.unit}` : ""}<small>{a.status}</small></td>
          <td class:best={a.rent !== null && a.rent === bests.rent}>{a.rent === null ? "–" : "$" + a.rent}</td>
          <td>{a.beds ?? "–"}/{a.baths ?? "–"}</td>
          <td>{a.floor ?? "–"}</td>
          <td>{a.facing.join(" ") || "–"}</td>
          <td class:best={a.place_score != null && a.place_score === bests.place_score}>{a.place_score ?? "–"}</td>
          {#each scored.filter((c) => shownCats.includes(c.key)) as c (c.key)}
            <td>{a.minutes?.[c.key] == null ? "–" : a.minutes[c.key]!.toFixed(0) + "′"}</td>
          {/each}
        </tr>
      {:else}
        <tr><td colspan="7" class="empty">No apartments match.</td></tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .filters { display: flex; flex-wrap: wrap; gap: 8px; align-items: end; margin-bottom: 8px; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; width: 100%; }
  .chips button.on { background: var(--fg); color: var(--bg); }
  label { display: flex; flex-direction: column; font-size: 11px; color: var(--muted); }
  label.inline { flex-direction: row; gap: 4px; align-items: center; font-size: 12px; }
  input[type="number"] { width: 80px; }
  .scroll { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; white-space: nowrap; }
  th, td { padding: 4px 6px; border-bottom: 1px solid var(--line); text-align: left; }
  th button { background: none; border: 0; font: inherit; font-weight: 600; cursor: pointer; color: inherit; padding: 0; }
  tr.sel { background: color-mix(in srgb, var(--fg) 10%, transparent); }
  tbody tr { cursor: pointer; }
  td.best { font-weight: 700; color: #1b8a3a; }
  td.name small { display: block; color: var(--muted); }
  .empty { color: var(--muted); text-align: center; padding: 16px; }
</style>
