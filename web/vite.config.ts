import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// In development the API, tiles and basemap assets come from the server
// (python -m uvicorn aptscout.app:app, with APTSCOUT_DEV_USER set).
const server = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: { "/api": server, "/tiles": server, "/basemap-assets": server, "/healthz": server },
  },
});
