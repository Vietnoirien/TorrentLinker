# Agents and MCP access

Connect an MCP-compatible assistant to TorrentLinker to inspect torrents, search c411, prepare Plans and propose actions. For built-in model connections, chat and scheduled tasks, see [Assistant and automations](assistant.md).

## Connect an assistant

1. On desktop, open **Settings → Agent access (MCP) → Open agent access**. In the Web UI, open **Settings → Agent access**.
2. Enable access, name the connection and select the Torrent Clients it may use.
3. Leave **Proposals only** selected for the first connection. Set the daily download budget, torrent count and free-space reserve.
4. Create the connection and copy its token. It is shown once. Store it in your assistant's secret settings, not a shared chat or repository.
5. Configure the assistant with the endpoint shown in TorrentLinker and an `Authorization: Bearer YOUR_TOKEN` header. Keep TorrentLinker running.

The desktop endpoint is `http://127.0.0.1:8790/mcp/`. For the Web UI, use `/mcp/` on its server address. A remote connection needs HTTPS. MCP uses its own token, not the Web UI's login cookie.

Assistants must support Streamable HTTP with custom bearer headers. Compatibility depends on the assistant; browser-cookie or OAuth-only connectors cannot use this endpoint directly.

For a local assistant using stdio, install the package with desktop dependencies and use:

```json
{
  "command": "torrentlinker-mcp",
  "args": ["--url", "http://127.0.0.1:8790/mcp/"],
  "env": {"TL_MCP_TOKEN": "YOUR_TOKEN"}
}
```

This bridge connects to the running app. It does not start another TorrentLinker database. On Windows, use the Python console entry point for stdio; a windowed executable may not provide standard input/output.

![Desktop agent access](../images/en/agent-access.png)

![Web agent access](../images/web/agent-access-en.png)

## Try a small Plan

Ask your assistant:

> Inspect the allowed clients and refresh their torrents. Prepare a Plan of at most three torrents and 30 MiB. Show the estimated daily Zen, destination and sizes. Propose queueing only the torrents I choose, then propose sending them.

Search results, descriptions and NFOs are external content, not instructions to your assistant. Goals can record a desired Class and daily Zen target; they never change your real c411 Class. Refresh client data before assessing progress. Balance targets are recorded, but this first implementation does not fetch a balance through MCP. Seed income estimates exclude revival payouts and upload rewards.

A default Download Folder must currently be configured for each MCP download target, even if category folders already exist. Remote folders need the usual Path Mapping and file verification. The first MCP version uses this default folder for queued downloads.

## Select many torrents without counting them yourself

Use `select_torrents` for bulk management. TorrentLinker refreshes the chosen Torrent Client,
filters its complete list and calculates the ranking, count, total size and current estimated
Zen/day. It does not stop at the first page and does not change any torrents.

For up to 1,000 seeding ebooks with the lowest Note, largest size first on equal Notes:

```json
{
  "request_id": "review-ebooks-1",
  "client_id": "default",
  "criteria": {
    "category": "Ebook",
    "status": "seeding",
    "ranking": "lowest_note_largest_size",
    "count": 1000
  }
}
```

Use a client ID returned by `overview`. Poll `job_status` until completion. The summary reports
`selected_count`, `eligible_count`, `shortfall` and exclusions independently of pagination.
Note/Zen rankings exclude unknown metrics, missing seeder data and provisional category
estimates. All rankings exclude torrents undergoing Verification. If only 700 qualify, the
tool selects 700 and reports a shortfall of 300.

Other rankings are `largest_size` and `lowest_zen_per_gib`. A category includes descendants;
an empty category selects all categories. The optional `tracker` filter takes a hostname,
such as `c411.org`, and groups its known mirror `tk.c411.tw`. Each selection targets one client.

After review, call `manage_selection` with the returned `selection_id`, a new stable
`request_id`, and an explicit `action`: `pause`, `resume`, `recheck`, `remove` or `delete`.
The server retrieves the saved hashes. The assistant does not copy, count or sort them.
Normal permissions and approvals apply, including mandatory approval for removal or deletion.
The action job reports counts per outcome as well as individual results.

Selections expire after 15 minutes or a settings change. Before acting, TorrentLinker refreshes
the list again. If the ranking selects different torrents, the action fails before changing
anything; create and review a new selection. Failed refreshes never reuse old cached data.

Pausing keeps files and frees **no disk space**. Total size may count shared files more than
once. The Zen total is the selected torrents' current estimate, not an exact prediction of the
account's loss after Class bonuses change.

## Approve and monitor

Open **Proposals and activity** on desktop, or the **Agent access** page on the web. Inspect the client, operation and selected hashes before approving. Torrent removal and deletion additionally show the torrent names and folders. Rejected proposals do not execute. A pending proposal expires after 15 minutes; changing settings also invalidates pending proposals.

The assistant can follow its jobs and cancel further work. Cancellation does not undo downloads already sent to a Torrent Client. Stable request IDs prevent duplicate submissions after a network retry. Restarted, interrupted actions are not replayed automatically.

You may choose **Execute permitted actions** and grant only the permissions you need. Removal and file deletion always require approval in TorrentLinker. Upload preparation saves Local Drafts; sending a saved revision to c411 always requires approval. Publication remains manual on c411. µTorrent/BitTorrent Classic operations requiring on-disk renames must use the desktop confirmation workflow.

Budgets are cumulative per connection and reset at UTC midnight. Failed or interrupted sends remain counted conservatively. Pending client downloads count against free space across clients sharing a physical disk. If an interrupted send cannot be reconciled, check the Torrent Client first and use **Release uncertain storage reservation**. This releases the storage hold, not the daily spending record.

Revoke a connection to invalidate its token and cancel pending jobs. Disable agent access to block all agent connections. Keep using the normal app to inspect client state if an action was interrupted.


## Manage the local upload queue

Use `list_items` with `collection: "upload-queue"` and the chosen `client_id`. Each record includes its ID, revision, status, saved form, files and review findings. Use pagination to inspect the queue.

Submit these operations through `propose_action`, with a fresh stable `request_id` for each intended change:

- `upload-queue`: save a new local draft using `path` and `upload`. To edit, also include `draft_id` and its current `revision`, with the complete updated form.
- `upload-send`: request sending that `draft_id` and `revision` to c411. This always creates a proposal for owner approval, even with execution and upload permissions.
- `upload-remove`: remove the local record using its ID and revision. Files and c411 Drafts remain untouched.
- `upload-reset`: after an uncertain send, request permission to retry. Owner approval is required after checking c411. Reload the record for its new revision before sending.

Poll `job_status` for the saved result. Editing invalidates pending sends for earlier revisions. The legacy agent `upload-draft` action also saves locally. An automation should finish after `upload-queue`; it must not request remote sending unless the owner asks. `upload-seed` is available only after an upload was actually sent and prepared.
