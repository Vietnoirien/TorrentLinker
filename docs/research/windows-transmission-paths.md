# Windows mapped drives and Transmission downloads

Reported during 1.0 polish on 2026-10-30. The reporter used the Windows desktop application, beta.23, with Transmission in Docker and an SMB share mounted as `Y:`. They agreed to try beta.27; no successful result on that release was established.

The settings screenshots show a mapped-drive Download Folder and a mapping from that drive path to `/downloads/complete`. The queue screenshot shows the corresponding UNC path instead, with Transmission's error `download directory path is not absolute`. The queue marks these sends as uncertain, so recovery must check the client before retrying.

## Reproduced cause

Search resolves its chosen destination before saving it in the queue. Windows can turn a mapped drive into its UNC equivalent at this point. Path Mapping previously compared only the configured strings. The UNC queue path did not match the `Y:` mapping and was forwarded unchanged to Linux Transmission.

`test_download_from_resolved_windows_share_uses_docker_path` exercises the real mapped-client wrapper and Transmission RPC adapter, with simulated Windows drive resolution and a simulated Linux RPC server. It failed with the exact reported error for both the mapping root and a child directory. No live tracker or reporter's client was contacted. The relevant resolution and mapping code is also present in beta.23 and beta.27; upgrading to beta.27 alone does not address this cause.

The mapper now tries resolved local mapping roots when no explicit string mapping matches. It resolves only existing local roots, preserves the longest matching root and path boundaries, leaves explicit mappings authoritative, and does not cache aliases across drive remounts. Remote client paths are never resolved on the app's machine. Existing queued UNC paths therefore use the configured container path on the next owner-authorized send.

The focused Transmission, Path Mapping, send, queue, folder and native Search suite passed 86 tests. Coverage includes unavailable roots, remounted aliases, nested mappings and explicit identity mappings. The Windows CI job now runs the Transmission adapter regression as well. This is a post-beta.27 fix; it does not alter published artifacts.

## Workaround for published builds

Use the full UNC path shown in the queue as the local side of the mapping, and retain `/downloads/complete` as the client side. Both forms must refer to the same actual directory. Do not use the Windows drive or UNC path as the Linux container destination. Check Transmission before recovering entries already marked uncertain; this fix does not automatically retry them.
