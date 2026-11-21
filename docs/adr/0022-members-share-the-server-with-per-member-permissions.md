# Members share the server with per-Member Permissions

Owners moving from Plex want their family and friends to use the server: to watch, with their own progress, and to ask for new films. Until now TorrentLinker had one person, the Owner: one password or a trusted proxy, and every session could do everything, including what acts on the Owner's c411 account, passkey and Torrent Clients. Issue #127 records the Owner's choices.

A Web or Docker server can now have Members. A Member has an account of their own and only the Permissions the Owner grants, one by one: there are no fixed roles. "Watch only" is a Member with Media Permissions and nothing else; an administrator is a Member given management Permissions such as accepting Requests or managing Members. Presets only pre-tick Permissions. Media is limited per Library Folder and Content Kind, by an Age Rating limit and by a separate adult-content Permission, off by default. A Member never downloads directly: they make Requests, or Wishes when no release is shown, that an Approver accepts. An accepted Request is sent to the Torrent Client at once, within the Member's optional caps (Requests per week, size per week, Requests pending). A shared screen can hold Viewers inside an account, each with their own progress and playlists, possibly narrower Permissions, and an optional PIN.

What acts on the Owner's c411 account stays the Owner's and is never a Permission: credentials and settings, Zen and the c411 profile, Upload, agent access and the Assistant's providers. The server enforces Permissions on every route and refuses what it does not know; hiding a tab is only presentation. Watch progress and playlists belong to a Viewer, not to the server. The desktop application stays the Owner's alone.

This supersedes the "one owner per server" scope of `docs/specs/web-070.md` and amends ADR-0016: behind `TL_WEB_AUTH=proxy`, a user header (such as `Remote-User`) is now read, but only from a connection whose own address is in `TL_TRUSTED_PROXIES`, and names a Member; without it the request is the Owner's, as before. Forwarded headers from any other address are still ignored.

## Considered Options

- **Fixed roles** (owner, family, guest): simpler to explain, but the Owner wants each Member set precisely, so roles became presets of Permissions.
- **Direct downloads with budgets**: rejected; downloads spend the Owner's c411 credit and ratio, so a person answers for each one.
- **A separate request service** (as Overseerr does for Plex): rejected; Requests start from Media's tracker rows and need the Catalogue, ReleaseScore and the Torrent Clients already here.
- **Proxy stays Owner-only**: rejected; Owners with single sign-on (Authentik, Authelia) expect their users to arrive signed in.

## Consequences

The Agent access model (Grants with client lists, propose-then-approve, budgets, audit) is the nearest existing piece, but it guards MCP job kinds only and must not stand in for people: a Media session's actor stays an Agent Grant. Progress and playlists need a migration from one per server to one per Viewer, and existing data becomes the Owner's. Sign-in moves from one in-memory password to stored accounts with per-account throttling; the startup password, or the proxy, stays the Owner's way in. Email notices need a mail server setting (SMTP, with an OVHcloud MX Plan preset). The measure of a Member's Assistant cap is left for a later decision.
