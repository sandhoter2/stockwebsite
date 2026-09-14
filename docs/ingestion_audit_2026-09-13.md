# Ingestion audit — 2026-09-13

Scope: centralized/shared-pipeline pass over `TelegramMessage` and `Trade` data
across all 76 channels, last 30 days (plus full-table checks where cheap).
Structural/type/pipeline issues were fixed in this pass; parsing-accuracy
issues are flagged for the next phase's per-channel specialist agents and were
**not** touched here.

## Snapshot

| metric | value |
|---|---|
| Channels | 76 |
| Total `TelegramMessage` rows | 1,881 |
| Total `Trade` rows | 250 |
| Messages in last 30 days | 1,547 |
| Trades with `posted_at` in last 30 days | 123 |
| Channels with 0 messages | 1 |
| Channels with 0 trades | 35 |

`manage.py parse_signals` (full re-run, no `--channel` filter) is idempotent:
0 new / 0 updated / 0 closed, trade count unchanged at 250 before and after.
`manage.py check` reports no issues. Full test suite: 53/53 passing.

## Fixed in this pass (structural/type/pipeline)

### 1. `Quote.asof` was a free-text `CharField`, not a real timestamp
Fixed — see the separate commit for `traderacker/models.py`,
`traderacker/management/commands/import_legacy_data.py`, and migration
`0006_quote_asof_datetime.py`. Summary: 42/42 existing `Quote.asof` values
(all in the legacy `"YYYY-MM-DD HH:MM IST"` format) parsed cleanly to aware
datetimes; 0 rows had to fall back to NULL. `import_legacy_data.py` now
parses `market.json`'s `asof` string into an aware datetime via a new
`as_asof_datetime()` helper instead of storing the raw string.

No other model field needed a type change: `Trade.date`/`posted_at`,
`Channel.created_at`, `PaperTrade.opened_at`/`closed_at`,
`Watchlist.created_at`, and `TelegramMessage.ts` are already proper
`DateField`/`DateTimeField` columns. `TelegramMessage.day_label` (e.g.
`'Sunday'`) and `stats()`'s internal `strftime('%Y-%m')` grouping key are
human-readable labels/API-response formatting derived *from* a real date
field, not a stored point-in-time value themselves — left as-is.
`accounts/` and `core/` apps have no models. No app persists a
`strftime()`/manually-built date string back into a model field.

## Findings — flagged, not fixed (out of scope for this pass)

### 2. `TelegramMessage.ts` is NULL for 5 messages
All 5 are channel 24 (`mid` 18284/18289/18290/18294) and channel 30
(`mid` 15713); the source text looks like malformed scrape captures (e.g.
`'17.7K\n07:48 AM'`, `'GIF\n182\n03:39 AM'`) rather than genuine messages
with a missing timestamp — i.e. the poller likely captured a
reaction-count/GIF-caption fragment instead of the real message body, and
never got a parseable `ts` for it. No messages had a NULL/garbage `ts`
outside these 5, and no `ts` was in the future or before 2015. **Not fixed
here**: this is a scraper/poller data-quality issue tied to specific
channels' post formats, not a schema/pipeline bug — flagging for a
per-channel/poller-side look rather than guessing at a fix.

### 3. "Trades posted before their channel existed" — 163 hits, but the check itself is unreliable
`Channel.created_at` is `auto_now_add` — it records when the `Channel` row
was **inserted into this DB** (i.e. import time), not when the Telegram
channel was actually created or first tracked. Since `import_legacy_data`
backfills years of historical trades against channels whose DB row was only
created recently (e.g. `Angel One Research` trades from 2025-06-27 against
a channel row created 2026-09-12), essentially every legacy-imported trade
trips this check. **Not a real integrity bug** — it's a limitation of using
`created_at` as a proxy for "channel existed," and there's no legacy field
(e.g. a channel-founding date) to backfill a true value from. Left as-is;
noting it so nobody re-derives this same false alarm later.

### 4. Duplicate/near-duplicate trades — schema-level constraint is working correctly; the dupes found are a matching-logic (parsing-adjacent) concern
The `UniqueConstraint(['channel', 'date', 'trade', 'entry', 'status'])` is
never actually violated — 0 exact-key duplicate groups, and 0 case-variant
`trade` strings bypassing it. However, grouping by `(channel, trade, date)`
alone (ignoring `entry`) turns up 39 groups with more than one row, e.g.:

- `(channel 44 "CryptoSignals-ish", 'STX', 2026-09-02)`: entries `0.257` and
  `None` — a second Open row was created because `parse_signals.py`'s
  upsert key includes `entry`, and a message that repeated the same symbol
  without a parseable entry price doesn't match the existing entry'd row.
- `(channel 51, 'SENSEX 75400 PE', 2026-09-09)`: entries `380.0` and `None`
  — same pattern.
- `(channel 3, 'BANKNIFTY 58500 CE', 2025-06-30)`: entries `495.0` and
  `499.0`, both Closed — two distinct legacy ledger rows for the same
  symbol/day with different entry prices (could be a genuine second
  call, or an import-side rounding/extraction difference in the original
  `ledger.xlsx`).
- `(channel 4, 'NIFTY 23500 CE', 2026-09-09)`: entries `160.0` (Closed) vs
  `None` (Open) — same entry-less-second-row pattern as above.

None of these are caught (or should be caught) by the constraint as
currently defined, because `entry` legitimately differs between the rows.
Whether an entry-less re-post of the same symbol/day should match the
existing Open trade instead of creating a new row is a call about
`parse_signals.py`'s upsert/matching heuristic, which is adjacent to
per-channel parsing tuning — **flagging for the per-channel phase** rather
than changing shared matching behavior here. Full list of the 39 groups is
reproducible via the audit query (grouping `Trade` by `(channel_id, trade,
date)` and filtering to `count > 1`).

### 5. Malformed `entry`/`target`/`stop_loss` values
None found: 0 trades with `entry <= 0`, 0 with negative `target`, 0 with
negative `stop_loss`, 0 with `entry > 1,000,000`. This app's data is clean
on this axis right now.

### 6. Messages that parsed to zero trades despite an apparent signal
315 of the 1,547 last-30-day messages contain a trade verb (`BUY`, `SELL`,
`CE`, `PE`, `LONG`, `SHORT`, etc.) per `TRADE_VERB` and aren't classified as
promo by `is_promo()`, yet `parse_message()` returned no signals. A random
15-message spot check shows this is overwhelmingly **not** a pipeline bug —
it's `parse_message()`'s regex set genuinely not covering these
per-channel formats:

- Placeholder levels the regexes don't handle: `"🎯 Target & Stop Loss :
  RA Team To Update"` (MarketWolf) — no numeric target/SL to match.
- Formats not covered by the current regex set: `"Buy Crude Oil 9200 Pe
  Above 230"` (verb + asset name + strike + right + ABOVE, a shape
  `RE_CASH`/`RE_OPT` don't combine), `"BUY BEL FUT (SEPT26) CMP 412-414 SL
  400 TGT 440"` (a CMP-range entry), `"Nifty 23450 Ce From 125 to 148.6"`
  (a "From X to Y" narrative rather than an actionable call).
- Genuinely not signals: news/macro digests (`Equity99` "Morning Alert..",
  a PlutusAdvisors global macro snapshot), a past-performance brag
  (`Stockpro Online` "SETL... delivered 52.49% upmove"), a part-profit
  narration on an already-open position (`Systematix Group`), a webinar
  registration link, and an off-topic joke message (`Swing Trader Vishal`).

This confirms the pipeline is behaving as designed ("no confident match →
no trade") rather than silently dropping clear signals due to a
plumbing bug. **Out of scope for this pass** by design — improving
`parse_message()`'s coverage of these shapes is exactly the per-channel
specialist agents' job, and the instructions for this pass explicitly
reserve `parse_message()`'s regex heuristics for that phase.

## What the next-phase (per-channel) agents should pick up from this report

1. Channels 24 and 30: a handful of scraped messages with no usable `ts`
   (item 2) — may be worth a poller-side look at what's being captured.
2. The `entry`-in-upsert-key matching behavior in `parse_signals.py` (item
   4) — decide whether a same-day, same-symbol, entry-less re-post should
   attach to an existing Open trade instead of creating a new row.
3. The 315 zero-signal messages (item 6) are a good source of real-world
   per-channel format gaps to prioritize when improving `parse_message()`
   channel-by-channel (`MarketWolf`, `Stockbox Trading`, `Ashika Calls`,
   `Systematix Group`, and several others show recognizable-but-unmatched
   shapes above).
