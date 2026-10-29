# c411 session downloads: what is established

Investigated on 29 October 2026 using unauthenticated, publicly served first-party frontend assets and the repository's dated measurements. No torrent was downloaded, no account endpoint was queried, no browser credential was read, and no rate-limit burst was performed.

**The website has a session-authenticated `.torrent` download route. Its numeric rate limit remains unknown. Nothing inspected establishes unlimited downloads.** A browser companion could technically invoke the website's existing operation, but production automation needs a supported contract and must obey refusals rather than switch credentials to evade them.

## Current website behavior

The public route manifest points the torrent detail page to `BYLfYng0.js`. Its download handler checks `/api/torrents/{reference}/check-integrity`, then fetches `/api/torrents/{reference}/download` with `credentials: "same-origin"`. The returned blob becomes the browser's `.torrent` download. This is a different transport from Torznab `t=get` with an API key. Inspection establishes the browser implementation, not the backend's complete authentication or throttling rules. [Route manifest](https://c411.org/_nuxt/BN0BChqL.js), [torrent detail implementation](https://c411.org/_nuxt/BYLfYng0.js).

The UI distinguishes obtaining a torrent descriptor from permission to download its payload. When the account's `canDownload` is false, the success message says the descriptor can still be obtained to seed files already owned, while downloading new data remains blocked. This can explain why a user sees a successful website download despite an account download restriction. It does **not** establish unrestricted request volume or unrestricted payload downloading. [Torrent detail implementation](https://c411.org/_nuxt/BYLfYng0.js).

There is also a separate `?free_dl=1` branch. It is chosen through a unit-download interaction and handles HTTP 402 when no unit is available, refreshing account state afterward. A companion must not silently select that branch: it can consume an account entitlement. Ordinary descriptor retrieval and a unit-download purchase/use must remain distinct. [Torrent detail implementation](https://c411.org/_nuxt/BYLfYng0.js).

No numerical session-download allowance was found in the inspected handler. The lack of a client-side counter says nothing about server-side throttling. The handler's generic handling of unsuccessful responses is also not evidence that the server cannot return 429.

## API documentation and dated observations

The current integration guide still documents 30 profile requests per minute per key within a 120-per-minute budget shared with Torznab. These are API request rules; they do not specify the session descriptor route's quota. The API permission definitions explicitly include descriptor downloads in `torznab:read`. [Integration guide implementation](https://c411.org/_nuxt/DlXcVhKv.js), [permission definitions](https://c411.org/_nuxt/Cmh6Hs5f.js).

The current Integrations UI supports up to five API keys. That is a website account capability; it does not establish that any particular TorrentLinker settings screen exposes all five clearly, nor does it grant five independent budgets for every endpoint. [Integrations implementation](https://c411.org/_nuxt/gKi5qL42.js).

The repository already contains stronger, but dated, observations from 22 October. They must be preserved with their limits:

| Operation | Recorded evidence | What remains uncertain |
| --- | --- | --- |
| JSON catalogue/search | Browser session and two keys reduced the same 1,200-request rolling-hour counter, with matching reset times. | Account versus IP scope was not separated; current server behavior was not remeasured. |
| Torznab descriptor download | One key's 31st rapid request returned 429 after 30 successes; a different key remained usable. The refusal reported a 60-second window. | Whether a longer window or other account-level limiter also applies today. |
| Longer download limit | Earlier refusals occurred below the observed short-window pace. | A longer limiter was inferred, not fully characterized; the application's 280-per-20-minute guard is not a published service guarantee. |
| Session descriptor GET | Not measured. A HEAD request returned 404. | Actual GET quota, account/IP/session scope, response headers and retry policy. HEAD does not establish GET behavior. |

Sources: [dated measurements](rate-limits.md) and [ADR-0008, including its evening correction](../adr/0008-several-c411-keys-each-within-its-own-limits.md). The earlier statements in those files about independent search budgets are superseded by their later observations. None supports using session authentication to add search capacity.

## Recommendation

Treat session descriptor delivery as an optional browser-based transport, **not an unlimited mode**. Keep API-key downloads as the existing baseline. Before implementing session delivery, seek c411's published or staff-confirmed policy for automated companion downloads, descriptor-grab accounting, the quota's scope and any longer windows. OIDC/API scope support may provide a more stable integration contract than website session endpoints.

If an ordinary, already-requested download is used for validation, inspect only its status, content type and quota/retry metadata; do not probe until a limit is exhausted. One success validates delivery, not capacity. A companion implementation should serialize/bound requests, respect `Retry-After` and 401/403/429, keep authentication inside the browser, verify account identity, and stop cleanly when the browser/session is unavailable. It must not retry an API quota refusal through the session as an automatic bypass.

The remaining questions are precise: does session GET have its own rate limit; does it share an account/IP limiter with Torznab; does obtaining the same descriptor again count as another grab; and is background automated use supported? The public assets inspected here do not answer them.
