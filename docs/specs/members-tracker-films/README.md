# Tracker films for Members: posters, films grouped, the Owner picks the release

Status: **spec complete** 2026-11-26, after a final review; no open questions. Builds on
ADR-0022 (Members, Requests, Wishes), the Médias tracker rows (`media_tracker.py`) and the
Requests page (`docs/specs/members-requests`). Nothing is implemented; a design preview of
the grid and film panel comes next, before any code.

## Problem

- The Member's **"Recherche c411 · consultation"** page (`member-workspace.js`,
  `MemberWorkspace.search`) lists raw releases: title, size and ReleaseScore, one card per
  torrent, with "Demander" on each. The Member therefore picks the release, sees release
  names they cannot judge, and the same film appears many times.
- The Médias row **"Disponible sur le tracker"** (`MediaTracker.tracker_rows`) shows posters,
  but only the newest films from the tracker cache, at most `ROW_LIMIT` = 60, one best
  release each. There is no way to see *all* the films the tracker has.
- Neither shows the film's description (synopsis) to a Member.

## Goal

A Member browses every film available on the tracker as **posters**, one poster per
**film** (its releases grouped), opens a film to **read its description**, and asks for the
film. The Member never chooses a release: the **Owner (or an Approver) picks the release**
when accepting.

## Model

- **Film** (existing sense, Médias): one title + year, identified by its TMDB id when known,
  else by normalised title + year. Releases of the same film on any Tracker group under it.
  Different releases of one film are never different films.
- **Tracker Film** (new term, proposed): a Film that has at least one release on a Tracker
  (from the Catalogue and the live tracker cache); Members never see one already in the
  Library (the Owner does, with a badge, decision 11). It
  carries its poster, year, genres, Age Rating, synopsis, and its releases (hidden from
  Members).
- **Request** changes meaning: a Member's ask for a **Film**, not for a release. It is
  created with no release; the Approver chooses one before accepting (pre-selected: the best
  release under the Owner's ReleaseScore profile, ties by Tracker order, then seeders,
  ADR-0025). An Owner-made Request still names its release directly.
- **Wish** stays: a free-text title for a film the tracker does not have (or the Member
  cannot find). Resolving a Wish = finding the Tracker Film, then choosing a release.

So a Member Request on a Tracker Film behaves like a Wish already resolved to a Film: the
release step is always the Approver's.

## What a Member sees

1. **Médias, row "Sur le tracker"** (was "Disponible sur le tracker", decision 22): drawn
   from the same film index as the grid, plus a **"Tout voir"** link opening the full page.
2. **Page "Films sur le tracker"** (replaces "Recherche c411 · consultation"):
   - a poster grid the Member can scroll to the end of every Tracker Film they may see
     (Age Rating limit, Content Kind: films only, never adult categories), loaded from the
     server page by page as they scroll;
   - genre rows and genre chips (decision 7), search by title, sorts of decision 10;
   - no release names, sizes, seeders, ReleaseScore or Tracker names.
3. **Film panel** (the existing Médias title panel): poster, title, year, genres, duration,
   Age Rating and the **synopsis**; "Demander à {Owner}" with the remaining quota; once
   asked, the Request state and "Annuler la demande".
4. Quotas (Requests per week, size per week, pending) are checked against the
   **pre-selected release's size** when the Member asks. On acceptance the Member is charged
   the smaller of the pre-selected and the chosen size: an Approver choosing a bigger
   release never costs the Member more quota.

## What the Owner / Approver sees

1. **Demandes page** (layout A, unchanged): a Member's Request shows the film; the
   inspector's release control lists the film's grouped releases (all Trackers), the best
   one pre-selected, each with ReleaseScore, size, seeders, Tracker, and its **torrent
   description** readable in the inspector. Accept sends the chosen release, as today.
2. The margin bar uses the chosen release's real size (`chosen_size`); the Member's quota
   alerts use the charged share (decisions 5 and 13).
3. The Owner opens the same "Films sur le tracker" grid with releases visible and
   downloads directly (their normal Télécharger flow).

## Data and performance

- Source: the per-Tracker Catalogues (all known torrents) merged with the live cache
  (`tracker-new`), grouped by Film. Grouping and poster lookup happen server-side; the page
  receives one row per Film with its poster; the Owner also gets the release count.
- The grouping is cached and refreshed with the Catalogue; posters, synopses, genres and
  Age Ratings come from the background identification job (decision 9) and the existing
  TMDB cache.
- The API for Members never returns release names, hashes or descriptions.

## Out of scope

- Series and other Content Kinds (films only for now).
- Members choosing releases or seeing torrent descriptions.
- Changes to the Owner's own Search page.

## Decided (owner, 2026-11-26)

1. **All films = every seeded film in the Catalogues**, old ones included, not only those
   passing the ReleaseScore threshold. A film with no seeded release is not listed.
   Metadata comes from the background identification job (decision 9); a film without
   metadata yet shows its title on a plain poster.
2. **Description = the film synopsis** (TMDB), with genres, duration and Age Rating.
   Torrent descriptions/NFO are shown only to the Approver, in the Demandes inspector.
3. **Both entry points**, one shared grid: "Tout voir" on the Médias row
   "Disponible sur le tracker", and the grid replaces "Recherche c411 · consultation".
4. **The Owner gets the same grid** with releases visible: opening a film lists its grouped
   releases (ReleaseScore, size, seeders, Tracker, description) and "Télécharger" on each.
   The Owner's Search page is unchanged.
5. **Quota**: checked against the pre-selected release when asking; charged
   min(pre-selected, chosen) on acceptance.
6. **Scrolling**: the Member can scroll through all films, loaded server-side page by page.
7. **Genres**: the "Sur le tracker" page is one row per genre (after "Nouveautés" and
   "Les plus partagés", which have no "Tout voir"). There is no grid of every genre at once:
   a grid always shows one genre, opened from its row's "Tout voir"; its chips switch to
   another genre, and "Affiner avec…" narrows to films of two genres (Animation + Familial).
   Changed 2026-11-26 after the first preview: one mixed grid put horror beside kids'
   animation. Two previews compare the grid's genre control:
   `members-tracker-films-preview.html` (A, a row of chips) and
   `members-tracker-films-preview-genre-menu.html` (B, a small line
   "Sur le tracker · Animation ▾" whose arrow picks the genre). **B chosen** by the owner on 2026-11-26.
   Choosing a film fills the pinned banner without moving the page; the Owner's grouped
   releases open in Médias' details dialog ("Releases (N)") rather than inside the page. The look comes from a preview that reproduces the real
   Médias interface (real components and CSS, real-shaped data), not a stripped mockup.
8. **Grouping**: by TMDB id once identified; until then by normalised title + year parsed
   from the release name.
9. **Identification**: a background job identifies every film once (poster, synopsis,
   genres, Age Rating), then only new Catalogue entries. The grid is usable meanwhile;
   films not yet identified show on plain title posters.
10. **Order**: newest on the tracker by default; also "Les plus partagés", "Année", "Titre".
11. **Films already in the Library**: hidden for Members; the Owner sees them with a
    "Dans la bibliothèque" badge and can pick a better release.
12. **Below the ReleaseScore threshold**: still listed; the best release is pre-selected
    and only the Approver sees a "sous le seuil" warning.
13. **Same film asked by several Members**: their Requests are linked (decision 17) and the quota is
    divided across all requesting Members (each is charged an equal share of the charged
    size, which is min(pre-selected, chosen)); everyone is notified when it is available.
14. **Unrated films**: the ADR-0022 rule stays; a Member with an Age Rating limit does not
    see films without a rating. Ratings fill in as films are identified; the Owner can set
    one by hand.
15. **Joining**: a Member may join an existing Request only while it is pending.
16. **Genres**: TMDB's French film genre list.

## Review: gaps found against the code (2026-11-26)

`member_requests.py` stores **one row per Member** (`requests`: account, infohash, release,
size…), keeps quotas as sums of that row's `size`, refuses a second Request for the same
infohash, and `answer()` overwrites `size` with the chosen release's size (accepting beyond
the quota with a note). The spec as decided conflicts with that in several places.

1. **Shared Request vs one row per Member.** "Share one Request" cannot be one row. Proposed
   model: each Member keeps their own row (own timeline, own notification, own cancel),
   linked by a `film` key (TMDB id, else normalised title+year). The Approver sees and
   answers one group: the answer moves every row together. A Member's charged `size` is
   the group's charged size ÷ number of rows, recomputed when a Member joins or cancels;
   a new column keeps the chosen release's real size for the Owner's margin bar.
2. **Charged size.** Today `answer()` overwrites `size`, so a bigger chosen release would
   raise the Member's quota use. Needed: `size` = charged (never above what the Member was
   quoted, lower if the Owner picks smaller), plus `chosen_size` for the margin bar.
3. **Duplicate guard** is by infohash; it becomes by film.
4. **Pre-selected release can change** between asking and accepting (new better release,
   seeders gone, torrent removed). The quote is a snapshot at ask time; the Approver sees
   the current best and the quoted one. A film that loses every seeded release before
   acceptance cannot be accepted until one returns, and can be refused with a note.
5. **Existing Requests and Wishes** (with infohash, no film key) stay valid; a migration
   adds the film key where the release can be identified, otherwise they stay as they are.
6. **Categories.** The Catalogue spans tracker categories (c411 2030, tr4ker 2000/2040…).
   The film list must name exactly which categories count as films, exclude series, music,
   software and adult categories, and apply the Member's Age Rating limit, the adult
   Permission and Library Folder/Content Kind Permissions (`sees_tracker`).
7. **Misidentification.** A wrong TMDB match shows the wrong poster and groups the wrong
   releases. The Owner needs a way to correct a film (re-match to another TMDB id, or
   split a release out), kept across re-identification.
8. **Releases without a year** or with an ambiguous title cannot be grouped by title+year;
   they stay unidentified and are listed under their release title, or left out.
9. **Search** matches the French title, original title and the release name.
10. **Cancel and refuse in a shared Request**: cancelling removes that Member's share
    (re-dividing the rest); the last cancel cancels the group; a refusal moves every row
    and gives every Member their slot back and the Approver's note.
11. **Expiry** (14 days pending) runs from the first ask; a join does not extend it.
12. **Privacy.** Members never see who else asked; at most "déjà demandé" for their own.
13. **Naming.** The Médias badge "Disponible" means in the Library; the row "Disponible sur
    le tracker" and the grid need a distinct name ("Sur le tracker") to avoid confusion.
14. **Documents to update with the build**: an ADR amending ADR-0022 (a Request names a
    Film), `CONTEXT.md` (Request, new Tracker Film), the en and fr guides, tests with fake
    catalogue, TMDB and tracker responses.
15. **Phone and accessibility**: the grid on the mobile shell, a visible "Charger plus"
    fallback beside infinite scroll, keyboard and screen-reader labels, `say()` strings.

## Decided after the review (owner, 2026-11-26)

17. **Shared Request model**: each Member keeps their own row (timeline, notification,
    cancel), linked by the film key; the Approver answers the group once; a Member's
    charged size = the group's charged size ÷ the number of Members; `chosen_size` keeps
    the real size for the Owner's margin bar (review items 1 to 3, 10 and 11 apply).
18. **Film categories**: c411 2030, 2060, 2070, 2080, 2090 and tr4ker 2000, 2040; the 6000s
    (adult) are excluded from this feature. The Catalogue showed tr4ker 2000/2040 hold
    non-films (PDF magazines, series, albums), so a tr4ker release is listed only when it
    is identified as a TMDB film; c411 2000 (series) and 2010, 2050 are not films.
19. **Correction**: the Owner re-matches a film to the right TMDB id from the film panel;
    the override is kept across re-identification.

## Decided in the final review (owner, 2026-11-26)

20. **Access**: the Films Permission lets a Member browse the grid and the row; the Request
    Permission shows "Demander"; Viewers browse without "Demander"; the Search Permission no
    longer gates it. `MediaCenter.sees_tracker` changes: today it hides every tracker film
    from a Member with an age limit (tracker films were unrated); with identified Age
    Ratings, the limit filters by rating instead (decision 14).
21. **Unidentified releases** (no year, no TMDB match): Owner only, under their release
    title, where the Owner can match them; Members see only identified films.
22. **The Médias row** comes from the same film index, grouping and rules as the grid, and
    is renamed "Sur le tracker" so it no longer clashes with the "Disponible" badge
    (review item 13).
23. **Per-release correction**: in the Owner's release list, "Mauvais film" re-matches one
    release to another TMDB film; kept across re-identification (with decision 19).

## Decided after the preview (owner, 2026-11-26)

24. **Viewers ask the account holder.** A Viewer on a Shared Screen may ask for a Tracker
    Film, if the account holder turned on "Peut demander des films" for that Viewer (off by
    default). The ask goes to the account holder, not to the Owner: it waits in the holder's
    Médias bell drawer, in a "Demandes de mon foyer" section, with a badge count.
    "Accepter" turns it into the holder's own Request to the Owner, on the holder's quota
    (decisions 5, 13, 17 apply from there); "Refuser" closes it with an optional note. The
    Viewer sees the state on the film ("En attente de Léa", then the Request's state).
    On the Owner's own account the Owner answers the same way, and accepting opens the
    release choice and downloads directly. This amends ADR-0022 ("Viewers never make
    Requests"): a Viewer still never makes a Request, only an ask to its account holder.
    A new glossary term is needed for the ask (proposed: **Household Ask**, "demande du
    foyer").

## Open questions

None.

## Next

Design preview of the landing page (genre rows), the full grid with chips, and the film
panel, built by copying the real Médias view and `media.css` with stubbed data.
