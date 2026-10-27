# aptscout

A labelled map for apartment hunting, starting with Chicago. Mark the places
you want to live near (grocery stores, lap pools, gyms, transit and more),
rank how much each kind matters, see the CTA bus and rail lines, and compare
the apartments you are interested in by rent, details, distance to what
matters and total weekly travel time (how often you go to each destination,
and how: CTA, walking, biking or driving). A web app on the tailnet.

- Brief: [docs/brief.md](docs/brief.md). Design: [docs/design.md](docs/design.md) (accepted).
- [web/](web/): the map and comparison UI.
- [server/](server/): the API and the apartment store.
- [docs/deploy.md](docs/deploy.md): what is built for deployment and the owner's steps.
- [data/](data/): the external datasets the app uses (nothing committed yet).

Your saved apartments, rents, rankings and notes are runtime data on the
host that runs the app. They never go in this repository.

## Verify

```sh
./scripts/verify      # repository + server tests, web type check and build
```

## License

MIT (`LICENSE`).
