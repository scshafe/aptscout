<script lang="ts">
  import { deletePhoto, getPhotos, uploadPhoto, type Photo } from "./api";
  import { resizeToJpeg } from "./photos";

  let { apartmentId }: { apartmentId: number } = $props();
  let photos = $state<Photo[]>([]);
  let busy = $state(false);
  let message = $state("");
  let open = $state<number>();

  async function load() {
    try {
      photos = await getPhotos(apartmentId);
    } catch {
      photos = [];
    }
  }
  $effect(() => {
    apartmentId;
    load();
  });

  async function add(e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const files = [...(input.files ?? [])];
    input.value = "";
    busy = true;
    message = "";
    try {
      for (const file of files) await uploadPhoto(apartmentId, await resizeToJpeg(file));
    } catch {
      message = "Could not upload (photos need a connection).";
    }
    busy = false;
    await load();
  }

  async function remove(id: number) {
    await deletePhoto(id);
    open = undefined;
    await load();
  }
</script>

<div class="photos">
  {#each photos as p (p.id)}
    <button class="thumb" onclick={() => (open = p.id)} aria-label="Open photo"><img src={`/api/photos/${p.id}`} alt={p.caption || "Apartment photo"} loading="lazy" /></button>
  {/each}
  <label class="add">
    {busy ? "Uploading…" : "+ Photo"}
    <input type="file" accept="image/*" capture="environment" multiple onchange={add} disabled={busy} hidden />
  </label>
</div>
{#if message}<p class="warn">{message}</p>{/if}
{#if open !== undefined}
  <div class="view">
    <img src={`/api/photos/${open}`} alt="Apartment" />
    <div class="row"><button onclick={() => (open = undefined)}>Close</button><button onclick={() => remove(open!)}>Delete</button></div>
  </div>
{/if}

<style>
  .photos { display: flex; flex-wrap: wrap; gap: 6px; }
  .thumb { padding: 0; border: 0; background: none; min-height: 0; }
  .thumb img { width: 72px; height: 72px; object-fit: cover; border-radius: 6px; display: block; }
  .add { width: 72px; height: 72px; border: 1px dashed var(--line); border-radius: 6px; display: flex; align-items: center; justify-content: center; text-align: center; font-size: 12px; cursor: pointer; }
  .view { display: flex; flex-direction: column; gap: 6px; }
  .view img { max-width: 100%; border-radius: 6px; }
  .row { display: flex; gap: 6px; }
  .warn { color: var(--warn); margin: 0; }
</style>
