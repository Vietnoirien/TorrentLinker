# File access in Settings preview (#119)

Throwaway preview of one new card inside the already approved Connections layout. It reuses #118's SFTP fields and identity confirmation; it is not a replacement Settings design. The question is where to expose reusable access, removal and workflow availability.

Run `python3 -m http.server 18780 --bind 127.0.0.1` from the checkout, then open `/docs/specs/remote-access-settings/prototype.html`. All state stays in memory. The controls use simulated responses and never connect to a server or save credentials. The bottom bar switches language, theme and example connection states.

The main implementation must share the editor with Transfers and enforce real server-identity, permission, path and active-transfer guards. A check in this preview is illustrative only.
