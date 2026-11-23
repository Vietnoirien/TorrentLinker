# tr4ker credits are a learned estimate

Zen is a dated table of c411 rules (ADR-0005), and Plans forecast it. tr4ker pays credits for seeding too, but it publishes no formula. The wiki says pay depends on size, category, seeder count and badge multipliers. The frontend adds that a torrent starts earning after 6 h of cumulative seeding since its last payout, and that payouts come in waves several times a day. There is no Hit-and-Run rule. A ratio below 0.5 blocks downloads. Credits buy upload volume in the shop (docs/research/tr4ker-credits.md).

The Profile shows tr4ker's balance, ratio (raw and bonus counters kept apart), shop prices and history right away. The app also logs every payout from `/api/me/sw-rewards` with the torrent's size, seeders, category and the badge multiplier, and fits an estimate from that log. The UI labels it "estimate from your payouts", never as a tr4ker rule. Until the log is large enough, tr4ker Plans rank by seeders, size and freeleech and show no earnings figure. Reseed requests that pay a fixed `reward` to the next seeders after `target_seedtime` are known amounts, so they show as such and feed Plans and Reseed.

## Considered Options

- **Balance only**: rejected; the payout log makes a usable estimate possible.
- **A hand-written heuristic**: rejected; it would look like a rule tr4ker never stated.

## Consequences

Zen terms stay c411's. tr4ker gets its own Credits terms. The payout log reading is unverified, because the research account's log was empty, so the issue needs a real non-empty response before the model ships.
