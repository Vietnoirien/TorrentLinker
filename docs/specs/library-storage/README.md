# Library storage: replace, Fichiers, organization, disks

Decisions from the 2026-11-27 grilling. Background is in `research-brief.md`.

## Write rule (new ADR, amends ADR-0004)
- The app may move, rename and trash files anywhere under the storage roots (`TL_STORAGE_ROOTS`), and create folders there.
- Every operation is journaled with undo. Delete always means trash.
- A seeded file moves or renames through its client, and every client is supported:

  | Client | Move | Rename |
  |---|---|---|
  | qBittorrent | `setLocation` | file paths renamed in the client |
  | Deluge | `move_storage` | file paths renamed in the client |
  | Transmission | `torrent-set-location move=true` | file paths renamed in the client |
  | rTorrent, µTorrent | stop, move, re-point, recheck, start; resume in `finally` | rename on disk, then the same re-point and recheck as Reseed |

- Moving a folder rewrites what is keyed by path: member folder grants and Link Folder manifests.
- Watch state, progress and playlists follow the film, never the path.

## 1. Replace (ships first)
- Médias, on the film's "Meilleure version sur le tracker" card, offers:
  - "Remplacer l'ancienne version";
  - "Attendre la fin de son partage", which only appears while the old release seeds and is enabled only with Replace on.
- The new release downloads next to the old one (same Library Folder and disk). It falls back to Download Folder rules when that disk lacks space above the margin.
- Once the new release is complete, it becomes the film's file. The old one is hidden from Médias and shows "en fin de partage" in Torrents and in Fichiers.
- The "Fin du partage" rule is a time and/or a ratio, with "l'un ou l'autre" or "les deux".
- When the rule is met (or at once without waiting), the torrent is removed without its data and its files go to the trash.
- Owner only.

## 2. Corbeille
- One trash folder per disk, so trashing is an instant move.
- Purged after 7 days by default; the delay is configurable.
- Each item offers Restore. "Vider maintenant" empties it.
- Trash space is counted separately in disk usage.

## 3. Fichiers (new sidebar entry)
- "File de téléchargement" leaves the sidebar and becomes a tab of Recherche, which frees its place for Fichiers.
- Tabs: Explorateur, Disques, Organisation, Corbeille, Tâches.
- Explorateur:
  - dual pane on desktop, one pane on phone;
  - drag between panels, F5 copy, F6 move;
  - a right-click context menu;
  - each row shows the film or poster and a seeding badge when they are known.
- Tâches is a background queue:
  - per-item progress and ETA;
  - cancel;
  - each item verified, nothing fails silently;
  - a persistent log.
- Conflict dialog: Ignorer, Remplacer (the old file goes to the trash) or Renommer, plus "appliquer à tous". Identical files (same hash) offer "Garder un seul".
- Access:
  - New member permission "Gérer les fichiers": move, rename and trash within the member's granted Library Folders.
  - Owner only: emptying the trash, Disques, settings and replace.
  - Every action is logged with who did it.

## 4. Disques
- Each disk is mounted separately (the new HDD too) and identified by `st_dev`.
- Shows space per disk, how much of the library sits on each, and the trash.
- Health from smartctl when the server is allowed to run it (setup shows how to allow it), plus an optional Scrutiny API setting. Alerts on a failing status or reallocated sectors.
- Placement rule:
  1. Keep a film's versions and a series' episodes on the disk they already share.
  2. Otherwise use the disk with the most free space above the 10% margin.

## 5. Organisation
- Jellyfin naming, editable per Library Folder with tokens (resolution, codec…):
  - films: `Titre (Année) [tmdbid-N]/Titre (Année) [tmdbid-N].ext`;
  - series: `Série (Année)/Saison 01/Série S01E01.ext`.
- Rename preview as a diff. Only the rows you confirm are applied.
- Seeded files are renamed inside the client.
- Per-client Link Folders cover torrents whose file layout or subfolders differ from the library. Each client's Link Folder setting says plainly what it is used for.
- Each Download Folder has a "Ranger automatiquement" toggle, off by default. On completion it renames and moves the release, still seeding, to the place the placement rule picks.

## Previews to build
Each preview copies the real view with a stubbed API, then adds the change.
1. Médias replace: film page toggles, timeline, Fin du partage, trash.
2. Fichiers Explorateur: dual pane, right-click menu, disk bars, seeding badges, conflict dialog, Tâches. Also the Recherche tab that now holds the download queue.
3. Disques and Corbeille.
4. Organisation and Liens: rename diff, template editor, per-client Link Folder settings.

## Previews
Run from the repository root, then open the sign-in URL (it signs in for you):

    .venv/bin/python docs/specs/library-storage/serve.py
    http://127.0.0.1:8767/library-storage-preview/signin

The real Web UI runs on a fake torrent client, with a 14-film library, generated posters and tracker upgrades written into the real stores. Every outside connection is refused. `preview.js` is the loader (bottom bar); each screen is a file listed in its `SCREENS` (loaded in order). The disks mirror the owner's: `/saves` (916 Go, 92 %), `/windocs` (916 Go, full, with a SMART alert) and the new 14 To Toshiba, ext4 label "library", mounted at `/library` (Films, Séries, Téléchargements, all empty). Names and sizes exist only in `fixture.py`; no real disk is read.

| Bar screen | File | What it shows |
|---|---|---|
| Remplacer | `replace.js` | Médias replace card, timeline, Fin du partage, Torrents badge. Scenarios: seeding, not seeding, disk full, Vue membre. |
| Navigation | `nav.js` | "File de téléchargement" leaves the real sidebar and becomes a tab of the real Recherche page; a "Fichiers" entry takes its place (the other screens inject it too). |
| Fichiers · Explorateur | `explorer.js`, `fichiers.js` | Dual pane (one under ~800 px), disk/folder picker, breadcrumb, free-space bar, posters, seeding badges, selection (click, Ctrl, Maj), drag, F2/F5/F6/F7/Suppr, right-click menu, move confirmation (instant or copy, through the client), conflict dialog (Ignorer, Remplacer, Renommer, Garder un seul, appliquer à tous). "Vue membre" limits the panes to the granted Library Folder and hides Disques, Organisation and "Vider maintenant". |
| Fichiers · Tâches | `tasks.js` | Queue with progress, ETA, cancel, ✓ vérifié per item, failures with their reason, log with who/when and Annuler on finished moves, renames, trashing and organisation. "Lancer 3 exemples" and "Échec de vérification" scenarios. |
| Fichiers · Disques | `disks.js`, `fichiers-storage.js` | One card per disk (used/free, 10 % margin, library/downloads/trash/other, films, SMART, temperature, smartctl or Scrutiny), smartctl hint, Scrutiny URL, placement rule with a live example, rebalance proposal that opens Tâches. Scenarios: "smartctl non autorisé", "Disque absent du conteneur" (host mounts /library, the container does not: the one step left is the compose volume, no formatting offered). |
| Fichiers · Corbeille | `trash.js` | Per disk: origin, who/when, size, "purgée dans N j", Restaurer, Vider maintenant (owner), retention setting (7 j). |
| Fichiers · Organisation | `organisation.js` | Jellyfin rename diff with checkboxes, "renommé dans le client", "nécessite un Dossier de liens", Appliquer la sélection, template editor per Library Folder with live example, "Ranger automatiquement" per Download Folder (with a simulated finished download). |
| Liens | `links.js` | In the real Paramètres › Connexions › Clients form, next to the real Link Folder field, a marked card explains what the Dossier de liens does for the selected client and whether it requires it. |

Data for the new screens is served by `serve.py` as `storage.json` (and `poster-N.png`, the same posters as Médias); the Fichiers page is `fichiers.html`, built on the app's `panel/base.css` and toast.
