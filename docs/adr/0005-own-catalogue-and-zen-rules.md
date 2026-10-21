# Our own Catalogue from the Indexer, and our own Zen rules

Zen Lab (zen.mma.dev) already offers a public catalogue endpoint of about 192 000 c411 torrents and a calculator, but it is undocumented, unlicensed and run by a third party, and its grab endpoint relays the user's c411 key through its server. We build our own Catalogue by crawling the user's Indexer through Torznab at the polite rate limit (a first crawl of hours, then incremental updates) and fetch .torrent files directly from c411, so the user's key never leaves their machine.

The Zen rules are our own implementation in one module, as a data table dated with its source. The size weight, the division by 7, prorating by seed time with a 30-minute minimum, Tanker class bonuses and the tree's +5% are confirmed by c411's official guide; the rarity and seed-age tables come from Zen Lab's reverse engineering, and the per-category factor the guide mentions is unknown. Zen Estimates are therefore shown as estimates.
