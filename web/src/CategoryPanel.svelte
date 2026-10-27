<script lang="ts">
  import { addCategory, deleteCategory, patchCategory, type Category } from "./api";

  let { categories, counts, onchange }: {
    categories: Category[];
    counts: Record<string, number>;
    onchange: () => void;
  } = $props();

  let adding = $state(false);
  let name = $state("");
  let colour = $state("#7a3db5");
  let error = $state("");

  async function toggle(c: Category) {
    await patchCategory(c.key, { visible: !c.visible });
    onchange();
  }

  async function create(e: SubmitEvent) {
    e.preventDefault();
    error = "";
    try {
      await addCategory({ name: name.trim(), colour });
      name = "";
      adding = false;
      onchange();
    } catch {
      error = "Could not add (is the name taken?)";
    }
  }

  async function remove(c: Category) {
    await deleteCategory(c.key);
    onchange();
  }
</script>

<ul class="cats">
  {#each categories as c (c.key)}
    {#if !c.transit}
      <li>
        <label>
          <input type="checkbox" checked={c.visible} onchange={() => toggle(c)} />
          <span class="dot" style:background={c.colour}></span>
          {c.name}
          <span class="count">{counts[c.key] ?? 0}</span>
        </label>
        {#if !c.builtin}<button class="link" onclick={() => remove(c)} aria-label={`Delete ${c.name}`}>delete</button>{/if}
      </li>
    {/if}
  {/each}
</ul>

{#if adding}
  <form onsubmit={create}>
    <input bind:value={name} placeholder="Category name" required maxlength="60" />
    <input type="color" bind:value={colour} aria-label="Colour" />
    <button>Add</button>
    <button type="button" class="link" onclick={() => (adding = false)}>cancel</button>
    {#if error}<span class="warn">{error}</span>{/if}
  </form>
{:else}
  <button class="link" onclick={() => (adding = true)}>+ category</button>
{/if}

<style>
  .cats { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
  li { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  label { display: flex; gap: 6px; align-items: center; flex: 1; }
  .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
  .count { color: var(--muted); margin-left: auto; font-size: 12px; }
  form { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
  .link { background: none; border: 0; color: var(--muted); text-decoration: underline; cursor: pointer; padding: 0; font: inherit; }
  .warn { color: var(--warn); }
</style>
