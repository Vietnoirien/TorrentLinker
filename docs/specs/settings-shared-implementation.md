# Shared Settings implementation

Issues #112 and #113 replace the desktop Settings widgets and Web setup forms with
`web/static/settings/view.html`. Desktop embeds this document in `SettingsView`;
Web embeds it in `#settings-frame`. Both use shared tokens and English/French labels.
Section headings and cards use one layout, with a consistent 16 px gap.

`SettingsWorkspace` validates Connections, General, Search & Matching and Zen groups,
manages client profiles, and delegates folder checks to the existing storage service.
Assistant and Agent access adapters expose the existing owner operations to the same
controls. Companion actions retain browser pairing and the desktop receiver.

Each section keeps a draft for the selected client. Failed saves retain edited values;
blank secret fields preserve saved credentials, while explicit clear controls remove
them. Managed Web secret files cannot be replaced from Settings. Responses expose
secret presence, not saved values. Desktop additional Indexer keys keep the existing
keyring names. Configuration-write failures restore prior credentials and settings.

Library Folders, Download Folders and Path Mappings keep their existing verification
and pending-work guards. Reading client folders translates saved path mappings and
fills a draft for review. Mapping tests report reachable torrent counts and download
folders the client cannot reach. Detection proposes mappings; saving verifies them.
Changing both sides of an existing mapping replaces the original pair.

Desktop Settings suspends agent execution and periodic settings writers while open.
Approvals are queued until the dialog closes. Client switching preserves Media's player
where the active client does not change. The dialog fits the available work area and
keeps Save/Discard reachable in short windows.

## Deliberate platform differences

- Desktop uses the system keyring; Web uses server secret storage and managed files.
- Desktop opens a local folder picker. Web browsing stays inside configured server roots.
- Interface size applies to desktop after restart. Browser zoom is controlled by the browser.
- Token and diagnostic exports use a native save dialog or browser download. Native token
  exports are written atomically with private permissions.
- Companion pairing uses the existing native or Web host handoff.

The old native Settings, client-manager, Assistant connection, Agent access and Companion
widgets are removed. The legacy Web setup markup and its renderers are also removed.

## Validation

Tests use temporary configuration, fake torrent clients, a memory keyring and mock model
providers. No live tracker or user torrent client is used. Shared Settings tests cover
first-run setup, saved-secret handling, failed-save drafts, multiple clients, preference
persistence, folder verification, context/sampling controls, agent tokens and Companion
handoff. Native rendering has been checked on Wayland in English/dark and French/light.
Full-suite and browser regression verification is in progress.
