# Tracker Series: the series catalogue, built like Tracker Films

Status: decisions from the 2026-11-27 grilling. Nothing is implemented, and no preview exists yet.

This follows Tracker Films (ADR-0028, `docs/specs/members-tracker-films`, `tracker_films.py`): the same film index, identified in the background, filled on demand, with Requests shared per film. The difference is that a series is made of seasons and episodes.

## Model
- **Tracker Series**: a series identified by its TMDb TV id, or failing that by its normalised title and year. It has at least one seeded release on a Tracker, from the Catalogues, seeded releases only.
- Kinds covered:
  - Séries TV;
  - Animation série and anime, which go to the Anime tab;
  - Séries documentaires.

  TV shows (Émissions TV) and adult categories are left out.
- How releases are grouped:
  - a season pack covers one season;
  - an Intégrale or multi-season pack covers every season it contains;
  - an episode release covers one episode.

  Names are parsed (`S01`, `S01E02`, `INTEGRALE`, `COMPLETE`) and then checked against TMDb's season and episode list.
- The background job identifies each series once with TMDb: poster, French synopsis, genres, Age Rating, seasons and episodes. After that it only handles new Catalogue entries, as Tracker Films does.

## What a Member sees
- **Placement**:
  - the Médias Séries tab gets a "Sur le tracker" row and a "Tout voir" page by genre;
  - anime series appear the same way in the Anime tab;
  - no release names, sizes, seeders, ReleaseScore or Tracker names are shown.
- **Series panel**: poster, synopsis, then series → seasons → episodes.
  - Each season shows whether the tracker has a full pack, episodes only, or an Intégrale that covers it.
  - Episodes show their title and synopsis and whether they exist on the tracker. Members never see their releases.
- **Library**:
  - a series fully in the Library is hidden from Members; the Owner sees it with a badge;
  - a partly owned series stays visible, its owned seasons are marked, and only missing seasons can be asked for.
- **Age Rating**: the same rule as films. A series without a rating stays hidden under a limit.
- **Permission**: "Films" becomes "Films et séries". "Demander" still needs the Request Permission.

## Requests
- A Member asks for the whole series or for chosen seasons, never for episodes.
- The Approver picks the releases:
  - pre-selected are the best season packs under the ReleaseScore profile;
  - an Intégrale is pre-selected instead when it covers the seasons asked for and scores better;
  - ties are broken by Tracker order, then by seeders (ADR-0025).
- Quotas use the pre-selected packs' size, and Members asking for the same season share one Request (key: TMDb TV id + season). Each is charged the smaller of the quoted size and the chosen size, split equally, as in ADR-0028.
- **"Suivre la série"**: when asking for a series that is still airing, the Member can tick this. Each new complete season pack that reaches the tracker then creates a pending Request for the Approver, never an automatic download, and the Member is notified.
- The Owner can also download single episodes from the panel.

## Open before implementation
- c411 and tr4ker category ids for each kind, read from the Catalogues.
- An ADR amending ADR-0028 (Request names a series and seasons, follows, the Permission rename) and glossary entries.
- A preview built on the real Médias Séries tab with fixture data.
