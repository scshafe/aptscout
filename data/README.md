# data

The external datasets aptscout will use. Nothing is committed here: datasets
are downloaded or built on the host that runs the app, and this directory
holds only this README (`.gitignore` and `tests/test_repository.py` enforce
it). Which of these are used, and how they are fetched and refreshed, is
decided in the design (`docs/design.md`).

Candidates (open questions in [docs/brief.md](../docs/brief.md)):

- **CTA GTFS static feed**: bus and rail routes, shapes and stops, published
  by the Chicago Transit Authority under its developer terms of use.
- **OpenStreetMap**: places by category (grocery stores, swimming pools,
  gyms and so on), through Overpass or a regional extract (for example a
  Geofabrik Illinois extract). ODbL: attribution required.
- **Map tiles**: OpenStreetMap's tiles under their usage policy, or free or
  self-hosted vector tiles (for example Protomaps or OpenMapTiles built from
  an extract).
- **Geocoding**: Nominatim under its usage policy, a self-hosted Nominatim,
  or the US Census geocoder.
- **Routing**: a self-hosted router (OSRM, Valhalla or OpenTripPlanner, the
  last with the CTA GTFS for transit times), or straight-line distance.

Never put the owner's apartments, rents, rankings or notes here: they are the
app's runtime data on the laptop, outside the repository.
