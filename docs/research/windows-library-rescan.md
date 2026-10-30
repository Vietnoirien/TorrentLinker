# Windows Library rescan investigation

Issue: [#51](https://github.com/Vietnoirien/TorrentLinker/issues/51).

The user reports a successful first scan followed by a freeze on subsequent scans in the Windows desktop app. On 2026-10-30 the available environment details remained "latest", probably Windows 11, probably local storage. The Windows version and storage location are unconfirmed; "latest" does not identify the installed build.

## Controlled reproduction

`tests/test_library_rescans.py` drives the native `MainWindow.scan` operation ten times in one process. It alternates cached scans with full rescans, changes fixture files between scans, and uses a simulated Torrent Client. A GUI heartbeat releases each client read, proving that the read does not block the event loop. Each pass checks the file sizes, restored scan controls and drained background jobs. Final checks compare the source bytes and close the window.

This test passed on Linux without a scan-code change. It does not reproduce the reported Windows freeze and does not establish its cause. It covers a small local fixture, not a large library, network share or the reporter's Torrent Client.

## Confirmed diagnostic defect

The existing opt-in stall monitor buffered stacks until the GUI recovered. A permanent freeze therefore produced no stack report. `test_permanent_stall_is_logged_before_the_gui_can_recover` failed while the GUI was held on a threading event, with no Qt events processed.

The monitor now writes a sample as soon as the threshold is exceeded and again as the stalled duration doubles. Each sample identifies the GUI and background threads and includes Python stacks without local-variable values. This can show a worker or lock involved in the wait. Recovery logs a short duration message. The regression passes before releasing the blocked GUI; it also verifies that a named background thread is present.

The Library scan, timeout, recovery, filesystem and stall-monitor regression set passed 45 tests on Linux. A dedicated Windows CI job runs the same-process rescan, timeout and stall-monitor checks, builds a diagnostic executable, smoke-tests its packaged media/MCP startup and shutdown, and retains the executable as `windows-library-diagnostics`. The packaged smoke test is separate from the ten-scan source test.

The [Windows job for `47e267b`](https://github.com/Vietnoirien/TorrentLinker/actions/runs/41121968333/job/124289977818) passed all 21 checks, including ten rescans in one source process, and the packaged smoke test. Its [diagnostic executable artifact](https://github.com/Vietnoirien/TorrentLinker/actions/runs/41121968333/artifacts/13008374611) contains the immediate stack logging. This is CI evidence on a clean runner, not a reproduction on the affected machine or a packaged ten-rescan walkthrough.

## Capture on the affected Windows machine

Use a build containing this diagnostic fix. Close other TorrentLinker instances, open PowerShell in the folder containing the executable, and launch:

```powershell
$env:TORRENTLINKER_STALL_MS = '1000'
& .\TorrentLinker.exe
```

Run the first Library scan and the rescans that normally freeze. If it freezes, leave it open for at least ten seconds so the background monitor can write samples. Find the log with:

```powershell
Get-ChildItem "$env:APPDATA\TorrentLinker" -Filter torrentlinker.log -Recurse
```

Preserve the stalled-thread sections with the exact app build, Windows version, scan type, Torrent Client, approximate Library size and local/network storage details. Review the log before sharing; stacks and surrounding application logs may contain local paths. Clear the opt-in setting afterward with `Remove-Item Env:TORRENTLINKER_STALL_MS`.

The Python monitor cannot report if the interpreter itself cannot schedule its background thread. A missing sample in that case needs a Windows process dump or native stack capture.

## Remaining acceptance

The freeze is not claimed fixed. Obtain a reproduced trigger or affected-machine stacks, then verify the correction with at least ten scans in the packaged Windows executable, responsive UI, preserved results/files and clean shutdown. Keep #51 open until that evidence exists.
