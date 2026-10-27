# web

The map and comparison UI (TypeScript, Vite, Svelte 5, MapLibre GL JS with
the PMTiles protocol). Design: `docs/design.md` section 8. Today (M6): an installable PWA (manifest, service worker: the app opens offline and the last lists stay readable; map tiles are not cached), apartments added offline wait on the device and sync when the connection returns, a + button and "Use my location" for adding on the spot, a phone-compass helper for the facing, and photos (resized to JPEG in the browser, which drops location tags). The service worker needs HTTPS, which the tailnet node provides. Before that (M5): transit rows say whether they come from the timetable or an estimate, and a banner shows when the routing graph is older than the CTA feed. Before that (M4): a Trips tab (destinations with trips per week, mode, time band, a what-if slider), a weekly travel time column and breakdown, an optional combined score, and how firmly the front-runner leads. Before that (M3): apartments (add with an address search or a pin, edit, status, detail with the score explained), a sortable and filterable comparison table, a side-by-side view, lines to the places an apartment counts; places by category with toggles, lap pool candidates to confirm or reject, favourites, notes, adding places and categories; the
basemap from the server's PMTiles file, the CTA rail and bus lines and stops
with toggles, attribution and the CTA feed validity footer.

```sh
npm ci
npm run dev      # proxies /api, /tiles and /basemap-assets to the server on :8000
npm run check    # svelte-check
npm run build    # writes dist/, which the server serves
```

No outside host is contacted by the browser: fonts, sprites, tiles and
libraries are all served by the app (design section 12).
