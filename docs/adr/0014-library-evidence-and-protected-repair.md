# Separate Library evidence and repair from ordinary Reseeds

The Library can inspect editable claims against MediaInfo and import old torrents as offline provenance. These are evidence, not authenticated authorship. Byte verification is distinct from size matching. Imported announces are never used to contact trackers.

Explicit compatible discovery also accepts Seeded Items. Selected Local Items can share a virtual manifest under one consistently mapped parent. This extends discovery without changing ADR-0002: no hardlinks or physical renames, and no downloads into existing Library files. Compatible discovery requires all target files to match before ordinary Reseed verification.

Experimental near-match repair is a separate workflow. It preserves ADR-0004 by creating its own independent copy under a newly created directory. Only that copy may receive missing data. The original can remain shared by other torrents because the copy does not share its inode. This first implementation deliberately excludes in-place conversion and reflinks.

The client receives the copy's target torrent stopped. An owner must explicitly confirm after the client's piece check agrees with the local diagnostic. State is persisted before external mutations. Failed or uncertain additions/starts require inspection, never automatic replay. Restarting the application never starts a pending repair. The original is the recovery source; unfinished copies are retained for review rather than automatically deleted.

Initial support is single-file v1 torrents with qBittorrent. Default thresholds are discovery heuristics and payload limits, not proofs of provenance, available peers, repair success or total network traffic. Representative media trials are needed before promoting this beyond an experimental workflow.
