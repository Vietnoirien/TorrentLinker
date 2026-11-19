# Approved interface backlog designs

The owner approved all three review areas on 19 November 2026: "Design is good go ahead."

- #79: Zen Catalogue, Plan, Seeding and the Zen band. Implementation: #90, #92, #93 and #94.
- #87: Settings Connections, Clients, Companion, Agent access, Assistant, General, Library Folders, Download Folders, Client Paths, Search & Matching and Zen. Implementation: #112 and #113.
- #88: the application shell and Documentation. Implementation: #114 and #115.

The approved [standalone prototype](https://github.com/Vietnoirien/TorrentLinker/blob/c871785deb9e1f4310826d5116d8db55e547a258/docs/specs/interface-backlog/prototype.html), [review paths and parity decisions](https://github.com/Vietnoirien/TorrentLinker/blob/c871785deb9e1f4310826d5116d8db55e547a258/docs/specs/interface-backlog/README.md) and [implementation boundaries](https://github.com/Vietnoirien/TorrentLinker/blob/c871785deb9e1f4310826d5116d8db55e547a258/docs/specs/interface-backlog/implementation.md) are archived at commit `c871785` on the separate prototype branch. Their pending-review wording describes the draft before this approval.

Use the existing shared palette and component language. Each production page has one bundled view for desktop and Web. Keep the approved designs of existing pages, including Profile. Do not copy the throwaway prototype's simulated services into production.

Verification uses public services and desktop/browser workflows, temporary settings and libraries, simulated Torrent Clients, both languages/themes, narrow viewports and a real-display desktop rendering check. No live tracker posting or user-library mutations are part of validation. Preserve drafts and selection across refreshes, and retain existing client ownership, secret storage, confirmation and cancellation rules.

The approval covers these designs. It does not change #89's outstanding packaged-platform playback measurements or the decision to retain native decoding.
