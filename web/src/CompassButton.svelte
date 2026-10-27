<script lang="ts">
  import { headingToCompass } from "./offline";
  import type { Compass } from "./api";

  let { onset }: { onset: (c: Compass) => void } = $props();
  let heading = $state<number>();
  let phase = $state<"idle" | "listening" | "denied" | "unsupported">("idle");

  function handler(e: DeviceOrientationEvent) {
    const ios = (e as unknown as { webkitCompassHeading?: number }).webkitCompassHeading;
    if (typeof ios === "number") heading = ios;
    else if (e.absolute && e.alpha !== null) heading = (360 - e.alpha) % 360;  // alpha is counter-clockwise from north
  }

  async function start() {
    if (typeof DeviceOrientationEvent === "undefined") { phase = "unsupported"; return; }
    const request = (DeviceOrientationEvent as unknown as { requestPermission?: () => Promise<string> }).requestPermission;
    if (request && (await request.call(DeviceOrientationEvent)) !== "granted") { phase = "denied"; return; }
    window.addEventListener("deviceorientationabsolute", handler as EventListener);
    window.addEventListener("deviceorientation", handler);
    phase = "listening";
  }

  function stop() {
    window.removeEventListener("deviceorientationabsolute", handler as EventListener);
    window.removeEventListener("deviceorientation", handler);
    phase = "idle";
    heading = undefined;
  }
  $effect(() => stop);
</script>

{#if phase === "idle"}
  <button type="button" onclick={start}>Use phone compass</button>
{:else if phase === "listening"}
  <div class="row">
    <span>Hold the phone flat, top edge pointing out of the window: <strong>{heading === undefined ? "…" : `${Math.round(heading)}° ${headingToCompass(heading)}`}</strong></span>
    <button type="button" disabled={heading === undefined} onclick={() => { onset(headingToCompass(heading!)); stop(); }}>Set</button>
    <button type="button" onclick={stop}>Cancel</button>
  </div>
{:else}
  <span class="meta">{phase === "denied" ? "Compass permission was refused." : "This device has no compass."}</span>
{/if}

<style>
  .row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 12px; }
  .meta { color: var(--muted); font-size: 12px; }
</style>
