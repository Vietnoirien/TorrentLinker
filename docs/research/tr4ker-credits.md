# tr4ker credits: earning, spending, forecastability

Sources: wiki (`/api/wiki/articles/credits`, `ratio`, `badges`, `les-inedits`), frontend bundle `assets/V6OUW5OR.js` (greps for credit, seedtime, multiplier, badge, shop, hit-and-run), live GETs of `/api/shop`, `/api/shop/history`, `/api/me/stats`, `/api/me/sw-rewards`. Only GET requests were sent. No personal values recorded.

Tags: [live] verified by a response, [fe] seen in the frontend bundle, [wiki] stated by the wiki.

## Earning

- Seedtime: [wiki] credits per kept seed; amount depends on torrent size, category and seeder count. No number, no formula.
- Seedtime payout rules: [fe] (support text on the ticket form) a torrent starts earning after 6 h of cumulative seed since its last payout; payouts come in waves several times a day (a delay of hours is normal); amount depends on size and rarity (bonus when few seeders). The category dependency is wiki-only. No rate per GiB or per hour is published anywhere.
- Fulfilling a request: [wiki] the bounty is paid once the upload is validated and confirmed; "the main source of credits". [fe] Reseed requests: the next N members to seed a torrent for `target_seedtime` (default 86400 s, 24 h) get a fixed `reward` credits each (`rewards_left`, `my_seedtime`). Per-torrent numbers come from the API at request time, not from a rule.
- Badge multiplier: [wiki] active badges raise every credit earned. [fe] badge objects carry `power_type: "credit_multiplier"` and `power_value` (percent, shown as "+N% CRÉDITS"). Values are per badge in the badge data. Not collected here.
- Staff grants: [wiki] manual.

## Spending (Shop)

- [live] `/api/shop` lists only upload items (public catalogue): +25 GB 400 cr, +50 GB 700, +100 GB 1200, +500 GB 4500, +1024 GB 8000. About 16 cr/GB at the small tier, 7.8 cr/GB at the largest. Items have `id`, `name`, `description`, `price`, `bonus_bytes`.
- [fe] The shop code also handles `freeleech_personal*` items (personal freeleech until a date, `personal_freeleech_until`) and an `invitation` item. They were absent from the live list, so their price and availability are not verified.
- [fe] Per-torrent freeleech: torrent detail carries `freeleech_price`; a POST to `/api/torrents/{slug}/freeleech` spends it. Price rule unknown.
- [fe] Bought bonus goes to `bonus_upload`, counted in the displayed ratio as (uploaded + bonus_upload) / (downloaded + bonus_download). Credits are the `money` field of the account summary.
- No exchange rate credit to byte beyond the table above. No credit to download credit item.

## Hit-and-Run / minimum seed time

- No Hit-and-Run rule found in the wiki, the general rules or the bundle (no hnr, min_seed, hit-and-run strings). [wiki] ratio minimum 0.5; below it downloads are blocked. Freeleech does not count downloaded bytes.
- The only seed-time thresholds seen: 6 h cumulative per payout [fe], 24 h default for reseed request rewards [fe].

## APIs for earnings

- [live] `/api/shop/history` returns `{days: []}` (empty for this account); [fe] pages show per day `earned` and `spent`, and `?day=YYYY-MM-DD` returns `transactions` with `amount`, `note`/`reason`, `movements`. This is the ledger: per-day totals, per-transaction reason. It is the only earnings history, and it is not per torrent.
- [live] `/api/me/sw-rewards?limit&offset` returns `{entries: [], total}` (empty). [fe] entry fields include `amount`, `seeders`, `size_bytes`, `seedtime_seconds`: probably one row per seedtime payout with the inputs. If populated, this is the best data for fitting a model. Not verified because the account's list was empty.
- [live] `/api/me/stats`: `summary` (uploaded, downloaded, raw_*, bonus_*, money, ratio_warning), `freeleech_count`, empty `snapshots` and `statistics`. [fe] snapshots expose `seedtime_seconds`, `uploaded`, `downloaded` per point, and per-torrent `seedtime_seconds` and `total_seedtime_seconds`. No credit rate field.
- No endpoint exposes a per-hour or per-torrent credit rate before payout.

## Verdict: B (estimable from observations), not A

No formula is published (wiki and bundle agree: size, category, seeders, badge percent, no constants), and the server computes payouts in waves. A c411 Zen style plan with fixed class factors cannot be built from public rules. A model is plausible because `sw-rewards` (if populated) and the shop ledger expose inputs and outputs.

Data a future logger would need:
1. Poll `/api/me/sw-rewards` and `/api/shop/history` (incremental, daily) and store each entry: amount, size_bytes, seeders, seedtime_seconds, timestamp.
2. Per torrent at payout time: category, size, seeder count (public torrent detail / Torznab), plus the user's active badge `credit_multiplier` percent.
3. Fit credits per payout against size, seeders band, category and multiplier; check the 6 h threshold. Show it as an estimate with the fit's sample count, never as a tracker rule.
4. Open question: confirm on an account with real seeding that `sw-rewards` is the per-torrent payout log.
