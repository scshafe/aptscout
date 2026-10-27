# aptscout agent notes

- A labelled map for apartment hunting in Chicago: places by category,
  ranked; the CTA bus and rail lines; apartments the owner is interested in,
  compared by rent, details, distance and total weekly travel time (trips
  per week to each destination, each with its own travel mode; a core
  feature). A web app on the tailnet (`web/`,
  `server/`); external datasets are described in `data/`. `docs/brief.md` is
  fixed; `docs/design.md` is the designer's (the first PR), kept in step with
  the code. Build nothing past the skeleton until the owner accepts the
  design.
- Privacy (public repository). The owner's saved addresses, rents, rankings,
  favourite places, destinations (such as the job's address), weekly trips
  and notes live only in the app's runtime data on the
  laptop. They never go in the repository, its fixtures, its issues, its PRs
  or its CI logs. Test fixtures use made-up addresses. Never write the
  tailnet's name: use `<tailnet>`. `tests/test_repository.py` enforces the
  tailnet name, that `data/` holds only its README, and that no database,
  backup or `.env` file is tracked.
- No service that costs money, needs an account or an API key without the
  owner's approval. Free services are used within their usage policies (for
  example OpenStreetMap tiles, Nominatim and Overpass).
- Deploying, tailnet nodes, Pocket ID clients and runner registration are the
  owner session's work: put what you need in the PR and ask.
- Public, MIT. CI runs on GitHub: wait for it before merging.
