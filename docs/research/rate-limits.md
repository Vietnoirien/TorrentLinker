# c411 rate limits

Measured on 2026-10-22 with one API key, using about 25 requests. `.torrent` downloads were not probed: each one counts against the account.

## What c411 documents

c411's integration guide states 30 requests a minute per key for the profile, counted within "les 120 par minute que partage la clé avec Torznab": 120 a minute per key, shared with Torznab. An account can hold at most 5 keys; the guide presents them as one per application (Prowlarr, Sonarr, Radarr, Jackett). It also mentions rate limits based on the user's tier.

## What the responses show

c411's JSON API (`/api/torrents`, `/api/user/profile`) answers with `x-ratelimit-limit: 1200`, `x-ratelimit-remaining` and `x-ratelimit-reset` (a Unix time). Torznab searches send no such headers but count in the same budget: three requests, one per endpoint, took `remaining` from 1,199 to 1,196.

After the announced reset time, `remaining` had not refilled and `reset` had moved 13 minutes later. The window rolls: `reset` is when the oldest counted request leaves it, an hour after it was sent.

## Downloads have their own limit

About 340 `.torrent` downloads between 12:20 and 13:01 left the budget at 1,188 of 1,200, so downloads do not count in it. Their limit is not reported. Earlier that day, downloads were refused for 19 minutes after 292 of them in 20 minutes, 846 in the hour.

## What the app does

Two queues (`src/torrentlinker/ratelimit.py`):

- Searches, Catalogue pages and caps go 0.5 seconds apart, c411's documented 120 a minute, while more than 100 requests are left in the hour. Below that, 3 seconds apart, which the hour can sustain. With none left, they wait until requests leave the window. The queue counts its own requests and trusts c411's headers whenever they are present.
- `.torrent` downloads stay 4.1 seconds apart in their own queue, and wait out a refusal (`send.py`).

Five live searches through the new queue took 2.5 seconds, against about 20 seconds with the single 4.1-second queue.

With several keys of the same account (ADR-0008), each key has its own two queues, and a key c411 answers with 429 rests while the others go on.

## The site's own session shares the same budget (2026-10-22, evening)

A tip from another user: the logged-in site seemed less limited, a dev-console script collecting hashes from the catalogue page's own requests. Measured with the user's logged-in browser and two of the app's keys, within a minute:

| Request | `x-ratelimit-limit` | `remaining` | reset in |
|---|---|---|---|
| Session: `/api/torrents?perPage=25` | 1,200 | 1,199 | — |
| Session: `HEAD /api/torrents/{hash}/download` (404, no grab) | 1,200 | 1,198 | — |
| Session: `/api/torrents?perPage=100` (after the page's own ~9 requests) | 1,200 | 1,188 | 733 s |
| Main key: `/api/torrents?perPage=100` | 1,200 | 1,187 | 725 s |
| Key 2: `/api/torrents?perPage=100` | 1,200 | 1,186 | 725 s |

The session and both keys draw on one budget: each request took one from the same count, with the same reset time. So the budget is per account (or per IP: all came from the same machine), not per key, and the session adds nothing to it. The session listing accepts `perPage=100`, as the keys do.

This contradicts "each key has its own budget" above and in ADR-0008, at least for the JSON API today; it may have changed since the morning's measures. Several keys still help with `.torrent` downloads only if their limit is per key, which was not measured. The session's download limit was not measured either: a `HEAD` on the download route answers 404, and a `GET` would be a grab.

## `.torrent` downloads: 30 a minute, per key (2026-10-22, evening)

Grabbing back to back with key 4 (Torznab `t=get`): 30 downloads went through in about 3 seconds; the 31st answered 429 with `retry-after: 43, 60`, `x-ratelimit-limit: 30`, `x-ratelimit-window: 60` and the body `Rate limit exceeded. Retry in 43 seconds.` Key 5, right after, downloaded 10 out of 10; key 4 was still refused ("42 seconds"). A first burst of 10 per key on keys 1 and 2 had all passed, with no rate-limit headers on successful downloads.

So downloads are limited per key, to 30 in a 60-second window, and only a refusal reports it. Five keys allow 150 a minute. The app's 4.1 seconds between downloads is about 15 a minute: half of one key's allowance.

The morning's refusal after 292 downloads in 20 minutes came at that 15-a-minute pace, below 30 a minute: there is probably a second, longer limit as well (846 had passed in the hour before). It was not reached here.
