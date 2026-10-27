<script lang="ts">
  let { onimported }: { onimported: () => void } = $props();
  let message = $state("");
  let confirming = $state<File>();

  async function run() {
    const file = confirming;
    confirming = undefined;
    if (!file) return;
    try {
      const resp = await fetch("/api/import?replace=true", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: await file.text(),
      });
      const body = await resp.json();
      message = resp.ok
        ? `Imported ${body.apartments} apartments, ${body.destinations} destinations, ${body.places} places.`
        : `Import refused: ${body.detail}`;
      if (resp.ok) onimported();
    } catch {
      message = "Could not import that file.";
    }
  }
</script>

<section>
  <h4>Your data</h4>
  <p class="meta">Everything lives on the host that runs aptscout and is backed up there. These copies are for you.</p>
  <div class="row">
    <a class="btn" href="/api/export" download>Export all (JSON)</a>
    <a class="btn" href="/api/export.csv" download>Comparison table (CSV)</a>
  </div>
  <p class="meta">Photos are not in the JSON; they are part of the host's backup.</p>

  <h4>Restore from an export</h4>
  {#if confirming}
    <p class="warn">Importing {confirming.name} replaces all of your apartments, destinations, categories and settings.</p>
    <div class="row"><button onclick={run}>Replace my data</button><button onclick={() => (confirming = undefined)}>Cancel</button></div>
  {:else}
    <input type="file" accept="application/json,.json" onchange={(e) => (confirming = e.currentTarget.files?.[0])} />
  {/if}
  {#if message}<p class="meta">{message}</p>{/if}

  <form method="post" action="/auth/logout"><button>Sign out</button></form>
</section>

<style>
  section { display: flex; flex-direction: column; gap: 8px; }
  h4 { margin: 8px 0 0; }
  .meta { color: var(--muted); font-size: 12px; margin: 0; }
  .warn { color: var(--warn); margin: 0; }
  .row { display: flex; flex-wrap: wrap; gap: 6px; }
  .btn { border: 1px solid var(--line); border-radius: 4px; padding: 6px 10px; color: inherit; text-decoration: none; }
</style>
