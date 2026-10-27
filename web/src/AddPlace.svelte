<script lang="ts">
  import { addPlace, type Category } from "./api";

  let { categories, at, oncreated, oncancel }: {
    categories: Category[];
    at: { lng: number; lat: number };
    oncreated: () => void;
    oncancel: () => void;
  } = $props();

  let category = $state("");
  let name = $state("");
  let error = $state("");
  const choices = $derived(categories.filter((c) => !c.transit));
  $effect(() => {
    if (!category && choices.length) category = choices[0].key;
  });

  async function save(e: SubmitEvent) {
    e.preventDefault();
    try {
      await addPlace({ category, name: name.trim(), lat: at.lat, lon: at.lng });
      oncreated();
    } catch {
      error = "Could not save the place.";
    }
  }
</script>

<form onsubmit={save}>
  <strong>New place here</strong>
  <select bind:value={category} aria-label="Category">
    {#each choices as c (c.key)}<option value={c.key}>{c.name}</option>{/each}
  </select>
  <input bind:value={name} placeholder="Name" required maxlength="120" />
  <div class="row"><button>Save</button><button type="button" onclick={oncancel}>Cancel</button></div>
  {#if error}<span class="warn">{error}</span>{/if}
</form>

<style>
  form { display: flex; flex-direction: column; gap: 6px; }
  .row { display: flex; gap: 4px; }
  .warn { color: var(--warn); }
</style>
