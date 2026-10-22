# Several c411 keys, each within its own limits

c411 limits each API key separately: 1,200 searches and Catalogue requests per rolling hour, and a separate limit on `.torrent` downloads (docs/research/rate-limits.md). An account may hold up to 5 keys. c411's integration guide presents them as one per application, and does not say whether one application may spread its requests across several.

On 2026-10-22 the user reported confirmation, through Zen Lab, which works with c411, that the 5-key limit is meant to be used this way. That confirmation did not come from a public c411 page; if c411 states otherwise, this decision should be revisited.

The app accepts up to 4 more keys of the same account besides the main one. Each key has its own two queues (`src/torrentlinker/ratelimit.py`): no key ever exceeds what c411 allows it. Each request goes to the key whose queue lets it go soonest. A key answered with 429 rests for the time c411 asks while the others carry on, and a request waits only when every key rests. A key refused with 401 or 403 is named in the error. Every key is removed from stored searches, URLs and error messages, as the main key always was. The main key remains the one used for the profile and for download URLs kept in the Catalogue, which are rewritten for the key that sends them.
