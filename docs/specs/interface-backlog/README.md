# Interface backlog design review

Draft, 19 November 2026. **Owner approval is pending.** This prototype does not authorize production changes to Zen, Settings, the shell or Documentation.

Open `prototype.html` directly in a browser, or serve this directory:

```sh
python3 -m http.server 18779 --bind 127.0.0.1 --directory docs/specs/interface-backlog
```

Open `http://127.0.0.1:18779/prototype.html`. The Review selector switches between the three design issues. The URL preserves the selected issue with `?area=zen`, `?area=settings` or `?area=shell`.

The question is whether these layouts and workflows close the inventory gaps while keeping the existing component language. The draft reuses the shared palette and the approved Community control spacing, panels, rows and badges. It proposes no alternative visual language. The review controls above the app are not product UI.

Everything is fictional and stored in memory. Reload resets the fixture. No application scripts, API calls, browser storage, filesystem pickers, tracker requests or real client operations are used. The state inspector shows the current fixture values. Existing approved Community, Library, Upload, Search, Assistant and Media pages are represented by placeholders when reached through the shell; they are not redesigned here.

## #79: Zen

1. Open Catalogue. Fetch one category, then all categories. Pause, or stop fetching and build the Plan.
2. Open Plan. Select or clear the whole Plan, change individual selections, sort, and queue selected downloads.
3. Review and send. Inspect Refresh first, choose a category destination, then simulate sending or stop. Switch Desktop/Web to compare the native-picker and server-browser explanations.
4. Follow Edit in Settings from the Zen Profile summary. The editable fields have one home in Settings, not a second form in Plan.
5. Open Seeding. Expand/collapse categories, sort, leave the page and return. The fixture retains expansion state; production must persist it per owner.
6. Inspect the Zen band on Catalogue, Plan, Seeding and Profile.

Resolved by this proposal: per-category Catalogue actions, both Plan selection actions, queueing on both hosts, send summary, Refresh first, folder prompt, stopping both stages, shared sorting, Seeding expansion persistence, and one location for Zen Profile fields.

Deliberate limits: speed tests measure the desktop or server where they run; directory selection uses that host's picker. The prototype illustrates the boundary without opening a picker. Profile keeps its approved #91 design.

## #87: Settings

Use every section in the left navigation. Edit a field, save, then cancel another edit. These are simulated actions, not a proposed new persistence model.

- Connections contains Torrent Client, Indexer and extra API keys, announce URL, TMDb and proxy. Test actions return fixture results.
- Clients supports switching, adding, editing and confirming removal.
- Companion shows pairing/revocation and the local receiver boundary.
- Agent access shows read-only defaults, one-time token display, revocation and proposal review.
- Assistant contains provider/model connection and run-limit controls.
- General contains language, theme, Media layout, adult content, diagnostics and desktop scaling.
- Library Folders, Download Folders and Client Paths show host-specific browsing, enabled folders, category routing, sequential downloads and mappings.
- Search & Matching includes category IDs, size tolerance, minimum Partial Match coverage, Ignored Files and Plan exclusions.
- Zen contains class, tree and badge bonuses, seed hours, torrent cap, disk margin and speed test.

Resolved by this proposal: Search & Matching and TMDb on both hosts, one Connections/Clients route, and one Zen field editor. Existing secret-redaction and ownership rules remain service requirements.

Deliberate limits: desktop keyring vs server-managed secrets, native vs server folder browsing, desktop folder import, Qt interface scaling vs browser zoom, and Companion pairing with the browser's local desktop receiver. No remote browser can pair an unrelated desktop automatically.

## #88: Shell and Documentation

1. Switch hosts and languages. Inspect sidebar labels, descriptions, update notice and client selector. At 390 pixels the navigation becomes a selector.
2. Open Torrents and choose All clients. Other pages require a specific client. There is no second All clients toggle inside Torrents.
3. Open the shortcut help from a placeholder page. Desktop keeps Ctrl+1..8, Ctrl+, and Ctrl+F. Browser-reserved shortcuts remain with the browser; visible navigation and search controls remain available.
4. Dismiss the update notice or open its release notes. The notice refers to the desktop installation or Web server version.
5. Open Documentation. Filter guides, follow links, use Back/Forward, and select a guide language independently of the shell language.
6. Inspect the shared Zen band through the Zen pages. Web-only Sign out and Activity remain host operations.

Resolved by this proposal: shared navigation labels and descriptions, one All clients selector, Zen band, update notice, guide filter, history and language controls. Deliberate limits are browser-reserved shortcuts, Web authentication/activity, and host-specific update installation.

## Review all states

For each issue, choose Empty, Loading and Error. Retry returns to the ready fixture. Choose 390 px, French and Light, then Dark. Inspect long form labels, tables, dialogs, folder prompts and the navigation selector. The same controls also work in a real 390-pixel browser viewport.

Empty/loading/error examples establish layout and copy treatment. Production must map real service states to them. The prototype cannot verify async races, filesystem permissions, Qt rendering, secret storage, packaging or tracker behavior.

## Decision record

No owner approval has been recorded. Review #79, #87 and #88 independently. Approval of one does not approve the other two. After approval, record the date and requested changes here; implementation issues #90/#92–94, #112–115 retain their own verification requirements.

## Draft rendering check

Chromium rendered all eleven Settings sections and all three issue views without JavaScript errors. Desktop captures and French/light 390-pixel captures were inspected. The narrow Settings navigation was corrected to scroll without shrinking labels; all three pages fit the viewport without horizontal page overflow. These checks establish that the draft is reviewable, not that production requirements have passed.
