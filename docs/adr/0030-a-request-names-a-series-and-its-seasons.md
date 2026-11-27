# A Request names a series and its seasons

ADR-0028 made a Request name a Tracker Film. Series raise the same problem, made worse by seasons: a Member cannot judge a season pack against an Intégrale, and the same series would appear once per release. The decisions are in `docs/specs/members-tracker-series/README.md`; this amends ADR-0028.

A **Tracker Series** is a series with at least one seeded release on a Tracker, identified by its TMDb TV id, or failing that by its normalised title and year. It is built like the film index, from the Catalogues' seeded releases, by `tracker_series.py`. Releases are classified from their names (`S01` a season pack, `S01E02` an episode, `INTEGRALE`, `COMPLETE` or several seasons an Intégrale) and checked against TMDb's season and episode list, so a mislabelled episode never makes a season look complete.

Category ids, read from the Owner's Catalogues on 2026-11-27:

| Kind | c411 | tr4ker |
|---|---|---|
| Séries TV | 5000 | 5000, 5040 |
| Animation série and anime (Anime tab) | 5070 | 5070 |
| Séries documentaires | 2000 | none known; the film categories 2000 and 2040 hold them, listed only as films |

c411's 5080 (Émission TV) and 5060 (sport), and the adult 6000s, are left out. tr4ker's 5000 also holds TV shows, so a tr4ker release is listed only once TMDb identifies it as a series.

A **Request** may name a series and chosen seasons, never episodes. Members asking for the same season share one Request (key: TMDb TV id and season), charged as ADR-0028 charges a film. The Approver picks the releases: the best season packs under the ReleaseScore profile are pre-selected, and an Intégrale instead when it covers the seasons asked for and scores better, ties going to the Tracker order and then to seeders (ADR-0025). A Member may tick "Suivre la série" on an airing series: each new complete season pack then creates a pending Request for the Approver and notifies the Member. Nothing downloads on its own.

The Films Permission becomes "Films et séries"; existing grants are kept.

## Considered Options

- **Requests per episode**: rejected; a Member asks for what they want to watch, and the Approver, not the Member, picks the files.
- **Automatic download of followed seasons**: rejected; a season is large, and the Approver's quota and choice still apply.
