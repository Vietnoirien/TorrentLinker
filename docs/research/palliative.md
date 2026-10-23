# c411 revival and soins palliatifs

Investigated on 2026-10-23. These findings come from c411's current public frontend bundles and three read-only metadata requests with TorrentLinker's existing API key. No torrent was downloaded, reseed request sent, or account state changed.

## What can be integrated

c411 has a complete revival workflow: discover torrents without seeders, identify torrents associated with the member, restart seeding, track the member's qualifying seed time, and record the eventual payout. Revival is a separate, conditional payment. It must not be added to the recurring Zen/day estimate.

The public [Soins palliatifs page](https://c411.org/torrents/palliative-care) uses [this frontend bundle](https://c411.org/_nuxt/DoBmQZuJ.js). Its summary distinguishes torrents awaiting revival, torrents revived in the last 30 days, and Zen paid in that period. Entry requires an approved torrent to remain without seeders for a configurable delay. The live summary reported `enabled=true`, `bountyEnabled=true`, and `delayHours=48`. These are current server settings, not permanent constants.

## Discovery and metadata

The user's `palliative=true` observation is correct for the website URL. The [listing client](https://c411.org/_nuxt/o7Qf9Ugw.js) translates that UI flag into `palliative=include` on `GET /api/torrents`. The dedicated revival page uses `palliative=only`. These values describe different request layers, rather than conflicting contracts.

| Request used by the official client | Purpose |
| --- | --- |
| `GET /api/torrents?palliative=only&palliativeAge=recent&sortBy=bounty&sortOrder=desc&page=1&perPage=25` | Recent revival opportunities; optional native `category` and `name` filters |
| Same request with `palliativeAge=archive` | Older opportunities; the page describes these as without seed for more than six months |
| `GET /api/torrents/palliative/summary` | Feature switches, entry delay, global counts and optional member summary |
| `GET /api/torrents/palliative/mine?page=1&perPage=25` | Torrents the member previously seeded, completed, or uploaded |
| `GET /api/profile/revivals?status=all&perPage=100` | Member revival records and qualification progress |

The dedicated page also allows sorting by `palliativeSince` or `size`. Its archive description explicitly says archived torrents remain available for cross-seeding and Torznab. The ordinary listing uses `palliativeTail=true` for a name search when the include flag is absent; response metadata distinguishes appended palliative matches and a fallback where no live torrent matches. Source: [listing client](https://c411.org/_nuxt/o7Qf9Ugw.js), [revival page client](https://c411.org/_nuxt/DoBmQZuJ.js).

The client consumes these fields:

| Object | Fields relevant to TorrentLinker |
| --- | --- |
| Torrent listing row | `infoHash`, `name`, `size`, `seeders`, `palliativeSince`, `bountyZen`, `palliativeCountdown` |
| Optional row `viewer` | `eligible`, `isUploader`, `ineligibleReason`, `keeperBonusZen`, `lastSeededAt`, `bountyAvailableAt` |
| Optional summary `viewer` | `revivable`, `bountyTotal` |
| Revival record | `id`, `torrent.infoHash`, `torrent.name`, `revivedAt`, `status`, `seedProgressSecs`, `requiredSeedSecs`, `qualifyDeadline`, `bountyZen`, `keeperBonusZen`, `paidAt`, `ineligibleReason` |

These are fields read by first-party code, not a published, versioned API schema. The [revival helper](https://c411.org/_nuxt/baMt2kFY.js) calculates the displayed personal payout as `bountyZen + keeperBonusZen`. That record amount should take precedence over a locally inferred share of a listing's bounty pool.

## Published reward rules

The [official Zen guide](https://c411.org/guide/tokens), implemented in [its guide bundle](https://c411.org/_nuxt/3EOLE6xJ.js) with [shared constants](https://c411.org/_nuxt/B9RO-iRf.js), publishes the following rules:

- The torrent's bounty pool starts at 5 Zen plus 0.5 Zen per GiB, with those two terms capped at 30 Zen. Each distinct member requesting seed after entry into soins palliatifs adds 2 Zen, capped at another 10 Zen. The published range is therefore 5–40 Zen before the personal class supplement.
- The member must be seeding when revival is detected and associated with the torrent by having completed it or obtained it on the site. The first three associated seeders share the pool.
- A Swarm Keeper receives 50% more on their personal share.
- Each recipient must personally accumulate 72 hours of effective seed time within 14 days after detection. The shared duration constant is 259,200 seconds.
- The rolling payout cap is 100 Zen per member over 24 hours; excess is deferred.
- A torrent pays at most once every 90 days. Its uploader does not receive the bounty.

These are guide rules, not a verified reproduction of backend rounding, ordering, or allocation. In particular, the guide says the first three share the reward without exposing all tie-breaking or rounding details. Prefer server-provided eligibility, deadlines, and personal payout amounts.

The [revival page](https://c411.org/_nuxt/DoBmQZuJ.js) displays `pending`, `paid`, and `void` records. Pending records show seed progress and deadline. Paid records show payment date and amount. Void records explain failure to reach the required seed time before the deadline. It offers no bounty claim button; the guide describes payment following qualification, with delayed payout possible under the rolling cap. This supports automatic payment, but does not establish the backend evaluation cadence.

The page's `POST /api/torrents/{infoHash}/request-seeds` action notifies former seeders and records demand. It is not the reward claim mechanism. TorrentLinker should not send these notifications automatically as part of discovery or planning.

## API-key access is the main remaining gap

The following bounded probe used the already configured c411 API key as `Authorization: Bearer`, the app's configured proxy, and requests separated by at least 4.2 seconds. Only status, field names, and public feature settings were printed.

| Endpoint | Observed result |
| --- | --- |
| `/api/torrents/palliative/summary` | HTTP 200; keys `bountyEnabled`, `counts`, `delayHours`, `enabled`, `last30d`, `viewer`; no member-specific viewer fields returned |
| `/api/torrents/palliative/mine?page=1&perPage=1` | HTTP 401 |
| `/api/profile/revivals?status=all&perPage=1` | HTTP 401 |

This key already supports existing app features, but its exact scopes were not independently enumerated in this probe. A 401 is not proof that every API key fails. It does establish that TorrentLinker cannot currently assume these personal endpoints work with its saved credentials. The official browser uses session authentication for them. Ask c411 whether `torznab:read` or `profile:read` keys can access the personal revival records, whether a different documented scope is required, or whether equivalent API routes are planned. Do not ask users to copy browser cookies into TorrentLinker.

Existing [catalogue research](full-catalogue.md) already verified Bearer access to the general JSON listing. This follow-up did not separately probe `palliative=only`, the complete revival row schema, or its pagination limits. A small authenticated listing sample remains useful before implementation, including a palliative row, a non-palliative row, and a member revival record if API-key access becomes available.

## Implications for the app

Treat revival as a cross-category status and filter. A film in soins palliatifs remains a film, so ordinary category and subcategory selection should combine with the revival filter.

Prioritize a full local Match that can pass Verification and Reseed without downloading. A zero-seeder torrent is not a reliable new download merely because its advertised bounty is attractive. Partial local content needs a separate warning about unavailable missing pieces.

Keep an advertised bounty pool, a member's potential payout, a pending qualified revival, and an actually credited payment distinct. A local 100% hash check proves the user can seed; it does not prove c411 has selected that user as an eligible recipient. The most useful monitoring fields are server eligibility, required seed time, progress, deadline, and paid status.

Before promising an optimizing Plan, establish personal API access and reward allocation semantics. The discovery filter and Library Candidate badge can be delivered earlier, with unknown eligibility shown explicitly. A future revival objective can rank verified local opportunities by server-reported potential payout and remaining seed commitment, while keeping recurring Zen/day separate.

The current app already requests `palliative=include` during native Catalogue refresh but discards revival fields. The planner excludes rows with fewer than one seeder. The current Zen calculation has no revival payout model. These are implementation observations, not evidence that the tracker lacks the capability.
