# Docker and a Web UI for 0.7.0

Checked on 2026-10-24. This is deployment research and a proposed scope, not an implementation plan approved for delivery. No services were installed or changed.

The user selected equal support for NAS/home-server and hosted-seedbox deployments in the first web release. Both deployment paths therefore belong in the 0.7.0 acceptance criteria. The remaining architecture and implementation scope below are recommendations.

## Existing decisions

TorrentLinker uses Python and PySide6 for its desktop interface. Its Torrent Client adapters already share an application port. Path Mappings translate prefixes between the application's filesystem and the Torrent Client's filesystem. They cover Library Folders, Download Folders and Reseeds. These decisions provide useful reuse for a server version. [ADR-0003](../adr/0003-python-pyside6.md), [ADR-0006](../adr/0006-one-list-of-path-mappings-detected-from-qbittorrent.md), [ADR-0009](../adr/0009-deluge-through-its-web-ui-with-labels-and-a-speed-guard.md).

Secrets currently use the desktop operating system's keyring through `get_secret` and `set_secret`. A headless deployment needs an explicit alternative rather than assuming a desktop session is available. [Current credentials implementation](../../src/torrentlinker/credentials.py).

## Verified deployment facts

### Network addresses depend on where TorrentLinker runs

Compose services on the same network discover each other by service name and connect to the container port. They should not persist a container IP, which can change on recreation. Separate Compose projects can join an existing external network. Consequently, `http://qbittorrent:8080` is a possible internal endpoint when that service name and port are configured; the user's browser does not need to resolve it. [Docker Compose networking](https://docs.docker.com/compose/how-tos/networking/).

Docker Desktop provides `host.docker.internal` for reaching services on its host. Native Docker Engine can add the equivalent host entry with `host.docker.internal=host-gateway`; Compose exposes host entries through `extra_hosts`. This address alone does not prove that a host service is listening on a reachable interface or that its firewall permits the connection. [Docker Desktop host access](https://docs.docker.com/desktop/features/networking/networking-how-tos/), [Docker run host gateway](https://docs.docker.com/reference/cli/docker/container/run/#add-host), [Compose networking](https://docs.docker.com/compose/how-tos/networking/).

Recommendation: test connectivity from the TorrentLinker backend, then test authentication separately. Present the endpoint as "Torrent Client address reachable from this server". Do not interpret `localhost` as the browser user's computer.

### Filesystem access and Path Mappings are separate

A bind mount makes a directory from the Docker daemon's host available inside a container. It cannot directly mount files from a remote Docker CLI user's machine. Docker Desktop supplies host-to-VM file sharing. Bind mounts are writable by default; `ro` makes the mounted view read-only. [Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/).

For example:

| Filesystem | Example path for the same file |
| --- | --- |
| NAS host | `/srv/media/Films/Example.mkv` |
| TorrentLinker container | `/library/Films/Example.mkv` |
| Torrent Client container | `/downloads/Films/Example.mkv` |

The host configures the two mounts. TorrentLinker maps `/library` to `/downloads`. A mapping only translates a name; it does not mount a share, grant access, or copy bytes. The implementation performs string-prefix translation. [PathMapper](../../src/torrentlinker/paths.py).

A browser directory picker grants the web application access to files on the browser user's device. That does not mount them in a remote Python process. The File System Access specification explicitly concerns the user's device and permission-granted file handles. A server-side Library Folder picker must therefore list directories visible to the backend. [File System Access specification](https://wicg.github.io/file-system-access/).

### Persistence and credentials need explicit storage

Docker volumes survive container removal, while a container's writable layer does not. Configuration, Catalogue state, queues and recovery journals need persistent storage and a backup procedure. [Docker volumes](https://docs.docker.com/engine/storage/volumes/).

Compose secrets expose granted secrets as files under `/run/secrets/`. `_FILE` variables are an image convention, not automatic application behavior. TorrentLinker would have to implement secret-file reading. File-backed Compose secrets also do not remove the need to protect their source files on the host. [Docker Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/).

Recommendation: retain keyring storage for desktop installations; add a server credential provider with explicitly documented persistence. Support Compose secret files for deployments managed as configuration. Decide separately how credentials edited through the Web UI are stored. Do not silently fall back to plaintext desktop settings.

## Proposed architecture and scope

Use one backend process for domain operations, long-running jobs and Torrent Client connections. Serve the Web UI from that backend, and keep credentials there. Closing a browser tab must not cancel a Scan or abandon Verification. Reopening it should recover job progress and results. This is a recommendation, not a property Docker provides.

Keep the current desktop interface while extracting reusable application services from Qt event handlers. Docker alone does not require replacing the desktop interface. noVNC is another possible route: it runs a VNC client in the browser, with a VNC server and a WebSocket connection or proxy behind it. It could expose the existing Qt desktop temporarily, but still needs authentication, persistent state and mounted files. It does not provide a native Web UI or remove desktop layout constraints. [noVNC project documentation](https://novnc.com/info.html).

For 0.7.0, I recommend a single-owner server with one active Torrent Client connection, matching today's domain model. Multiple browser sessions can control that same installation. Multi-user accounts, isolated libraries and simultaneous management of several clients should be separate decisions.

The setup flow should distinguish these checks:

1. Can the backend reach and authenticate to the Torrent Client?
2. Can the backend read the selected Library Folder?
3. Does the Path Mapping resolve the same sample files in both views?
4. Does the requested operation require write access, and which process performs it?

Allow a clearly labelled remote-management mode when the API is reachable but files are not mounted. It can support API-only features while disabling local Scan, local comparison, hashing and Upload preparation. Do not claim that entering a seedbox URL makes its disk available.

Remote management, Zen and Search are the initial candidates for that mode. Download and Plan safety need separate work. Existing collision checks inspect paths through `Path.exists`, and Plan construction reads filesystem capacity and Download Folders. An unmounted remote path must never mean "empty directory" or "no collision". A user-entered space budget cannot establish overwrite safety. Either obtain adequate remote capacity and collision evidence through client capabilities or refuse the operation until storage is accessible. [Send checks](../../src/torrentlinker/send.py), [desktop orchestration](../../src/torrentlinker/gui/main_window.py).

Use approved filesystem roots for the server folder picker. Validate resolved paths and symlinks on the backend. Run with deliberate filesystem permissions, keep API keys out of browser responses, and require authentication before exposing file listings or torrent management. Preserve explicit confirmation for deletion and disk renames. These are proposed server requirements.

## Permission limits to preserve

A read-only TorrentLinker mount protects against writes through that mount. It does **not** prevent a connected Torrent Client from deleting files through its own writable filesystem when the user confirms "Delete torrent and files". The current app delegates that action to the client's API. The Web UI must explain that deletion happens on the Torrent Client's machine. [ADR-0004](../adr/0004-the-app-downloads-but-never-writes-files-it-did-not-create.md), [Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/).

Archive extraction and confirmed µTorrent disk renames require backend filesystem writes. Their availability must follow the configured writable roots. Keep per-torrent confirmation, local verification and recovery journals for the µTorrent exception. [ADR-0007](../adr/0007-unpack-an-archive-to-reseed-its-contents.md), [ADR-0013](../adr/0013-confirmed-disk-renames-for-utorrent.md).

Before promising release scope, validate deployment on a same-host shared Docker network, a native host Torrent Client, and a remote seedbox with and without mounted storage. Test a reconnect during Verification and a container recreation with persisted state. None of these deployment tests were performed for this research note.

## Proposed delivery sequence

1. Extract job ownership, connection handling and user-confirmation workflows from Qt into application services shared by desktop and web. Keep one backend process initially because current locks and rate limits are process-local. Persist job state and reconcile interrupted operations before retrying mutations.
2. Build setup for both deployment targets. Detect API capabilities separately from filesystem access. Test reverse-proxy URL prefixes, TLS and authentication for hosted services. Provide a backend folder browser, mapping preview and per-operation permission checks for mounted storage.
3. Implement authenticated Web UI access to Torrents, Zen, Search and the Download Queue. Resolve remote download collision checks before enabling sends without a mount. Resolve remote capacity reporting and budgeting before enabling the Planner in that configuration. Do not substitute container free space for seedbox free space.
4. Expose Library and Upload workflows when the backend can access the required files. Document where a hosted-seedbox provider must allow a storage mount or execution of TorrentLinker alongside the client. Equal deployment support does not imply that a client API supplies file contents.
5. Package one Docker image with persistent configuration and state, a server credential provider and documented Compose examples for both deployment targets. Test browser reconnection, container restart, large catalogues and both read-only and writable media mounts. Keep the desktop application supported.

Release scope should explicitly settle whether every desktop Upload editor and preview must have web parity at 0.7.0. Multiple simultaneous Torrent Clients, multiple isolated users and built-in SSH/SFTP storage access remain separate proposals.
