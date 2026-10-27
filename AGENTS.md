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
- Deployed by the runner lane (`dev.toml [deploy]`): a merge to `main` builds the
  `Dockerfile` and deploys `deploy/stack/` on the laptop, served on the tailnet
  only at `https://aptscout.<tailnet>/`; watch it with `gh run watch`
  (`docs/deploy.md`). The host validates `deploy/stack/` against infra's
  allowlist. Tailnet nodes, Pocket ID clients, the host's `.env` and the
  runner are the owner session's work: put what you need in the PR and ask.
- Public, MIT. CI runs on GitHub: wait for it before merging.

<!-- scshafe-dev:begin landing -->
## Verify and landing

Managed by scshafe-dev: `dev adopt` and `dev update` refresh this section from `dev.toml`; change `dev.toml`, not these lines.

Before finishing, both of these must pass:

```sh
./scripts/verify
dev check .
```

How a change lands:

1. Work on a branch and open a PR.
2. Run the two commands above. If the repository is private, GitHub Actions does not run for it: verify locally and say in the PR what you ran. If it is public, wait for CI to be green.
3. Merge your own PR with a merge commit, one change at a time: `gh pr merge <N> --merge --subject "Merge #<N>: <title>"`. Never squash or rebase (both are off on the repository), and pass `--subject`: `gh pr merge` does not make the `Merge #N: <title>` subject by itself.

The project's agent may merge its own PR and push `main`; there is no approval gate.
<!-- scshafe-dev:end landing -->
