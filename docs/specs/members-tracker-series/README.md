# Tracker Series: the series catalogue, built like Tracker Films

Status: decisions from the 2026-11-27 grilling. Nothing is implemented; a preview on the real pages exists (see "Preview").

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
- **Permission**: the existing "Séries" Member Permission gates the tracker series catalogue; "Films" is not renamed. "Demander" still needs the Request Permission. (Decided after the preview, 2026-11-27.)

## Requests
- A Member asks for the whole series or for chosen seasons, never for episodes. A season the tracker only has as single episodes (no full pack) cannot be asked for: it is greyed, and "Suivre la série" creates the Request when a full pack lands (decided after the preview).
- The Approver picks the releases:
  - pre-selected are the best season packs under the ReleaseScore profile;
  - an Intégrale is pre-selected instead when it covers the seasons asked for, scores better, and the asked seasons make up at least half of it (decided after the preview); otherwise the season packs;
  - ties are broken by Tracker order, then by seeders (ADR-0025).
- Quotas use the pre-selected packs' size, and Members asking for the same season share one Request (key: TMDb TV id + season). Each is charged the smaller of the quoted size and the chosen size, split equally, as in ADR-0028.
- **"Suivre la série"**: when asking for a series that is still airing, the Member can tick this. Each new complete season pack that reaches the tracker then creates a pending Request for the Approver, never an automatic download, and the Member is notified.
- The Owner can also download single episodes from the panel.

## Open before implementation
- c411 and tr4ker category ids for each kind, read from the Catalogues.
- An ADR amending ADR-0028 (Request names a series and seasons, follows, the Permission rename) and glossary entries.
- Category ids (read from `catalogue_sync.py` SUBCATS and `tr4ker-categories.json`; to confirm against the live Catalogues):
  - c411 native child, Torznab id: Série TV 7 → 5000, Animation Série 2 → 5070, Série Documentaire 57 → 2000 (it sits under the films root, so it shares 2000 with other kinds: split it by its native child id, not the Torznab id). Left out: Émission TV 5 → 5080, Sport 9 → 5060.
  - tr4ker slugs under the `series` root: `series-tv` (21), `series-animees` (23), `series-manga` (24, Mangas Animés). Left out: `series-emission` (22), `series-sport` (25). tr4ker has no documentary-series category: its series documentaires sit under `films-documentaire` (15) and need TMDb to say they are series.
  - `tracker_categories.CHILDREN` already maps -2, -7 and -57 to the `series` slug.
- Questions the preview raises:
  - A Member cannot ask for an episodes-only season (no full pack): it is greyed, and "Suivre la série" is what catches the pack when it lands. Confirm.
  - Rule "pre-select the Intégrale when it covers the asked seasons and scores better" also fires for one season out of five (e.g. S1 of Breaking Bad would pre-select a 5-season Intégrale and quote its size). The preview applies the rule as written; the Approver can switch to the pack. Add a size guard?
  - Anime series show in the Anime tab under the "anime" Permission, documentary series in Séries; the Permission rename only touches "Films" (now "Films et séries").

## Preview
`.venv/bin/python docs/specs/members-tracker-series/serve.py`, then open http://127.0.0.1:8768/tracker-series-preview/signin (starts in about a minute: the Library is scanned first). The real Médias, Demandes and Réglages pages are served with fixture data (`fixture.py`: 3 Library series, 17 Tracker Series with generated posters); the scenario bar at the bottom picks the role (Propriétaire, Membre, Membre avec limite d'âge) and jumps to each screen. Everything the preview adds carries an "Aperçu" badge. Nothing reaches a tracker, TMDb or a torrent client (sockets to anything but this server are refused).
- `series.js` / `series.css` run inside the real Médias frame: the "Sur le tracker" row on Séries and Animés, the Tout voir page (the Tracker Films landing and grid, fed with series), the seasons under the banner, the Member's request sheet.
- `preview.js` / `preview.css`: the scenario bar and the Approver's inspector for a series Request on the real Demandes page.
- `settings.js`: the "Films et séries" label on Réglages · Membres.
- `screens/`: PNG captures (390×844 and 1600×950).
