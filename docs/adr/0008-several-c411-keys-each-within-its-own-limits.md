# Several c411 keys, each within its own limits

c411 limits each API key separately: 1,200 searches and Catalogue requests per rolling hour, and a separate limit on `.torrent` downloads (docs/research/rate-limits.md). An account may hold up to 5 keys. c411's integration guide presents them as one per application, and does not say whether one application may spread its requests across several.

On 2026-10-22 the user reported confirmation, through Zen Lab, which works with c411, that the 5-key limit is meant to be used this way. That confirmation did not come from a public c411 page; if c411 states otherwise, this decision should be revisited.

The app accepts up to 4 more keys of the same account besides the main one. Each key has its own two queues (`src/torrentlinker/ratelimit.py`): no key ever exceeds what c411 allows it. Each request goes to the key whose queue lets it go soonest. A key answered with 429 rests for the time c411 asks while the others carry on, and a request waits only when every key rests. A key refused with 401 or 403 is named in the error. Every key is removed from stored searches, URLs and error messages, as the main key always was. The main key remains the one used for the profile and for download URLs kept in the Catalogue, which are rewritten for the key that sends them.

Several activities may use the keys at once: a Plan being sent, Catalogue updates, Library searches and Reseeds. Requests the user waits for (searches, file checks, Reseeds) pass before background ones on every key, and never wait more than about 30 seconds for c411: if every key is resting longer, they stop with the time to try again, while a background send waits on. Making a new Plan stays disabled during a send, since it would replace the Plan being sent and its saved progress. A torrent that a Reseed and a Plan both add is refused as "already in qBittorrent" by whichever comes second.

## Correction, 2026-10-22 evening

Measured again (docs/research/rate-limits.md): the 1,200-an-hour budget for searches and Catalogue pages is shared by every key of the account, and by the site's own logged-in session; extra keys do not add to it. Each key does have its own `.torrent` download limit: 30 in any 60 seconds, plus a longer one (a key was refused after 292 in 20 minutes). So the extra keys speed up Plan sends, not searches. Each key's download queue keeps to 30 a minute and 280 in 20 minutes, and a Plan send spreads over every key (#28). The per-key search queues stay: each trusts c411's `x-ratelimit-remaining`, which reports the shared budget.
