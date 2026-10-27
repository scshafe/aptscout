# aptscout: the owner's brief

A labelled map for apartment hunting. The owner marks and ranks the kinds of
places they want to live near, sees Chicago's CTA bus and rail lines, saves
the apartments they are interested in with rent and details, and compares
those apartments by distance to what matters.

## The owner's request (2026-10-27, verbatim)

> creating a labelled map that can be used to label things like grocery
> stores, public transportation, lap pools (swimming), gyms, etc. for
> apartment hunting. I want to be able to rank various types of things that I
> want to be by, and then compare distances to those things as a part of my
> apartment hunt. In particular, I'm thinking about chicago, so i also want
> to be able to see the CTA bus and rail lines. I'd also like to be able to
> mark addresses as interested for rent, so I want to be able to show the
> price, and possible also details like floor, and cardinal direction facing
> (in apartment buildings).

Added the same day (2026-10-27, verbatim):

> I want to be able to list how many times per week I'll be going to various
> things: job, grocery store, gym, etc. and then to be able to pick my
> commute strategy (public transportation to work for example, while walking
> to gym) and then to be able to minimize my weekly commute time on that
> basis

## Owner decisions (2026-10-27)

- **Repository:** public, MIT licence, named aptscout.
- **A tailnet web app** on the production laptop. It reaches production
  later through the runner lane; until then `dev.toml` declares
  `[deploy] lane = "none"`.
- **Chicago first:** the CTA bus and rail lines are part of the map.

## Goals

- **Rank what matters.** Categories of places (grocery stores, lap pools,
  gyms, transit and so on) carry the owner's ranking, and apartments are
  compared by distance to them.
- **Compare apartments.** Each apartment the owner is interested in shows its
  rent and details (such as floor and the direction it faces) next to its
  distances and score.
- **Minimize weekly travel time (core feature).** The owner lists their
  destinations with how many trips a week they make to each. A destination
  is either a specific place (such as the job) or a category (such as
  "grocery store", meaning the best one near the apartment). Each
  destination has its own travel mode: CTA transit, walk, bike or drive (for
  example transit to work, walking to the gym). For every candidate
  apartment the app computes the total weekly travel time, the sum over
  destinations of trips per week times the round-trip time, and uses it to
  rank the apartments.
- **See the city.** The map shows the labelled places, the apartments and the
  CTA bus and rail lines together.

## Rules

- **The owner's data stays out of git.** Saved addresses, rents, rankings,
  favourite places, destinations (such as the job's address), weekly trips
  and notes live only in the app's runtime data on the
  laptop. They never go in the repository, its fixtures, its issues, its PRs
  or its CI logs. Test fixtures use made-up addresses.
- **Never write the tailnet's name.** Use `<tailnet>` (for example
  `aptscout.<tailnet>.ts.net`). `tests/test_repository.py` enforces it.
- **No money without the owner.** No service that costs money, needs an
  account or needs an API key without the owner's approval. Free services
  are used within their usage policies, and their attribution (for example
  OpenStreetMap's) is shown.
- **Owner steps.** Deploying, tailnet nodes, Pocket ID clients and runner
  registration are the owner session's work. Put what you need in the PR and
  ask.

## Open questions for the design

The designer lists a recommendation for each in the design's "Owner
decisions" section; the owner decides.

1. **Map tiles:** OpenStreetMap's own tiles (their tile usage policy limits
   heavy use and requires attribution), free hosted vector tiles, or
   self-hosted tiles built from a regional extract (Protomaps, OpenMapTiles).
   The map library (Leaflet, MapLibre GL) follows from this.
2. **Place data:** OpenStreetMap through Overpass or a local extract, versus
   paid place APIs (which need the owner's approval). How to find *lap*
   pools specifically: OSM `leisure=swimming_pool` with `sport=swimming`,
   access and length tags are patchy, so whether to combine sources (Chicago
   Park District pools, gym listings) and let the owner confirm or add pools
   by hand. Which categories ship first, and whether the owner can add their
   own categories and places.
3. **CTA data:** the CTA GTFS static feed for bus and rail routes, shapes and
   stops; its terms of use; how often to refresh it and how a refresh is
   noticed. Whether realtime data (CTA Bus Tracker, Train Tracker) is in
   scope at all.
4. **How distance is measured:** straight line, walking distance over the
   street network, or CTA transit time; per category or chosen by the owner.
   Self-hosted routing (OSRM, Valhalla, OpenTripPlanner with the CTA GTFS)
   versus something simpler, and what each costs to run on the laptop.
5. **Ranking and scoring:** category weights; nearest one versus nearest N
   in a category; a maximum acceptable distance per category; specific
   favourite places (a chosen gym or pool) that count instead of the nearest
   of a kind; how the score is shown and explained.
6. **Apartment records:** which fields: address, unit, rent, floor, the
   direction it faces, beds and baths, the listing link, status (interested,
   toured, applied, rejected and so on), notes, and possibly photos. The
   geocoding source for addresses (Nominatim under its usage policy, a
   self-hosted Nominatim, the US Census geocoder) and correcting a pin by
   hand.
7. **Comparison UI:** a side-by-side table and the map together; sorting and
   filtering; how distances and scores sit next to rent and details.
8. **Sign-in:** Pocket ID, like the other tailnet apps; single user or
   several (for example a partner who hunts too).
9. **Phone use:** the app used on a phone while touring apartments: adding an
   apartment on the spot, the map on a small screen.
10. **Data storage and backup:** where the runtime data lives on the laptop,
    the database, how it is backed up and restored, and export.
11. **Deploy:** the runner lane, the stack under infra, the tailnet node, and
    how the external datasets are fetched on the host.
12. **Privacy rule:** what counts as the owner's private data; keeping it out
    of logs; whether sending the owner's addresses to outside services (a
    public geocoder or router) is acceptable or everything that sees them
    must be self-hosted.
13. **Stack:** language and framework for `server/` and `web/`.
14. **Chicago only, or any city** with Chicago first.
15. **How weekly travel times are computed:** transit and walking times by
    time of day (a weekday rush-hour commute differs from a Saturday
    grocery run); schedule-based routing on the CTA GTFS, such as a
    self-hosted OpenTripPlanner, versus a simpler model (for example walk to
    the nearest stop plus a typical ride time); bike and drive times; how
    long a full recompute takes when a destination or apartment changes.
16. **Which place a category trip uses:** the nearest place of that kind to
    the apartment, the best one by travel time in the chosen mode, or a
    chosen favourite (a specific gym) the owner sets.
17. **Weekly time versus the category rankings:** how the total weekly
    travel time combines with the category rankings (question 5) and with
    rent: one combined score, weekly time as the main ranking with the
    rest as filters, or separate sortable columns.
18. **Milestones.**

## The designer's job (first PR)

1. Write `docs/design.md`: the data sources (tiles, places, CTA, geocoding,
   routing) and their licences and usage policies, the data model, the
   weekly travel time model (destinations, trips, travel modes), the
   ranking and scoring model, the map and comparison UI, sign-in, storage
   and backup, privacy, the deployment on the runner lane, and milestones.
   List every decision the owner must make in an "Owner decisions" section.
   Don't decide those yourself.
2. Keep `scripts/verify` and `dev check .` passing.
3. Build nothing past the skeleton until the owner accepts the design.
