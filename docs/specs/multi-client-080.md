# Named Torrent Clients for 0.8.0

The user approved desktop and web support equally, multiple instances of the same engine and mixed engines, and a custom name for each connection. Plans can target one client or distribute downloads across selected clients.

Each profile has an immutable ID, an editable name, connection details, Path Mappings and Download Folders. The existing configuration becomes the `default` profile and retains its existing keyring or deployment-secret names. Additional profiles use their own credential names. The default destination is separate from the stable identity of pending work.

Queues, Verifications and saved Plans are scoped by client ID. Distributed Plan rows retain their destination when saved and restored. The same torrent hash on two clients represents two independently manageable instances. Combined Zen estimates deduplicate hashes because an extra client instance does not establish another account reward.

The desktop offers a target selector, a client settings list, and an All clients view in Torrents. The web offers the same profiles and a combined overview. Actions name their target client; an unavailable client does not silently redirect work. Replacing or deleting a connection with pending work is blocked. Renaming is allowed.

Plan destinations accept per-client download budgets. Zero uses available storage after the configured free-space margin. Shared mounted disks have one physical-space budget. Placement uses round-robin assignment within those budgets before the existing Zen selection heuristic. Estimates remain provisional. The web continues to require verified mounted destinations for safe sends.

This replaces the single-client scope of the 0.7.0 web specification. It extends ADR-0006's single Path Mapping list to one list per Torrent Client; each list still applies consistently to Library paths, Download Folders and Reseeds.

Verification uses temporary storage and fake clients for migration, credential isolation, identical hashes, destination retention, management, and shared-disk budgets. Existing adapter integration tests remain applicable.

## Separate follow-up

The user reported a 14 TB scan across four HDDs taking about 30 minutes and asked to discuss scan performance and UI responsiveness after this implementation. Investigation and changes to disk exploration are deferred to that discussion.
