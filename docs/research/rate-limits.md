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
