# Proposed implementation and verification boundaries

These boundaries are a proposal for owner review, not an approval record. Production work waits for the corresponding design issue's approval.

Each approved page should have one bundled HTML/CSS/JavaScript view hosted by Qt WebEngine and the Web UI. Reuse the shared palette, transport and bilingual label conventions. Existing service ownership, client targeting, run limits and confirmation rules stay in the services; a view must not grant itself new operations.

Zen uses the existing Catalogue, Plan and Seeding services. Seeding expansion is owner-specific. Sorting must preserve selection by stable torrent identity. Fetch cancellation and send cancellation remain distinct operations. Refresh first precedes the send review's final target calculation. Missing destinations require a category-specific Download Folder; already completed sends survive stopping.

Settings edits need draft preservation across section changes and failed requests. Save validates the complete affected settings group. Existing stored secrets are represented by status, never exposed as field values. Unchanged secrets stay unchanged. Removing a Client must respect existing references and confirmations. Desktop-native pickers, keyring, scaling and Companion receiver actions use explicit host commands; Web directory browsing stays within configured roots.

The shell owns client selection, navigation, theme and language. All clients is available only for aggregate views supported by the service, currently Torrents; leaving aggregate mode restores a specific client before any client-scoped action. Documentation gets a shared guide index and history, with independent guide language and validated links. Update notices distinguish the server installation from a desktop installation.

Automated verification should use public services, temporary settings/libraries and simulated clients. Cover state restoration, cancellations, confirmations, client switches and failure recovery. Browser checks should cover French/English, both themes, 390 pixels and keyboard focus. Each completed implementation needs a real-display desktop check. No live tracker posting, real Torrent Client mutations or user-library changes belong in these checks.

Do not copy this throwaway JavaScript into production. Replace the old renderer only once equivalent public workflows pass. Document deliberate platform limits in the parity inventory.
