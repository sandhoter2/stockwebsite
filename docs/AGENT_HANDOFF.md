# Agent handoff — per-channel parsing specialists

**Purpose:** this is the single pickup point for channel-parsing agents. Read this
file and the target channel's `Channel.style_notes` before touching any code.
Do **not** re-derive from scratch what a previous agent already concluded.

**Last updated:** 2026-09-14 00:05 CDT by the QwenWork session that audited agent
cost waste (§3 and §5 are new, §6 is a new run log with its first entry — the
Stockpro Online verification run). Sections 1–2 were reconstructed from git + the DB.

**State anchor at the time of writing:**

| thing | value |
|---|---|
| branch / HEAD | `main` @ `aece464` (2026-09-13 23:05) |
| baseline commit | `85fc9ed` 20:19 "Initial commit: baseline before agent-driven development" |
| commits on 2026-09-13 | 40 (first: `85fc9ed` baseline, last: `aece464`) |
| `traderacker/signals.py` | 654 lines, sha256 `c37cfc079b4a…cc815d` (pre-circuit-lock code was `86828794368e…`) |
| tests | 84 total, of which **46** are in `SignalParserTests` (`traderacker/tests.py:107-…`) — **84/84 passing** in 28.6s warm / 41.6s cold, verified on the 2026-09-14 00:20 working tree (81/81 at `aece464` before the circuit-lock change) |
| data | 76 channels · 2,978 messages · 221 trades (34 closed) · ₹53,425 realized |
| channels with `style_notes` written | **7** (69 still empty) |

Verify the anchor before trusting section 3's shortcut rules:

```bash
cd /Users/mamathap/Downloads/django
git log -1 --format='%h %ad %s' --date=format:'%Y-%m-%d %H:%M'
shasum -a 256 traderacker/signals.py
```

If `signals.py`'s hash still starts `c37cfc079b4a`, nobody has changed the shared
grammar since this note was written and the cheap path in section 3 is safe. An
`86828794368e…` hash means you are on code from before the circuit-lock close path
(section 6, 00:20 entry) — the 3 extra `SignalParserTests` cases will fail there.

---

## 1. Status board — who worked on what, and when

The seven channels below have been through a specialist. Each one's durable output
lives in **`Channel.style_notes`** in the DB (2.5k–4.7k chars of format KT, written
by the agent that owned it) plus named regression tests in `SignalParserTests`.
Read the notes with:

```bash
sqlite3 -readonly db.sqlite3 "SELECT style_notes FROM traderacker_channel WHERE id=39;"
```

| # | Channel | style | msgs | trades | realized ₹ | landed in | last touched |
|---|---|---|---|---|---|---|---|
| 3 | Angel One Research | mixed | 60 | 28 | 20 | `3f18942` | 2026-09-13 21:22 |
| 24 | Motilal Oswal - Official | cash | 47 | 19 | 0 | `e76e950` | 2026-09-13 21:52 |
| 26 | NIRMAL BANG OFFICIAL | mixed | 42 | 14 | 689 | `5e3111b` → `477c274` | 2026-09-13 22:50 |
| 30 | Options Train (SEBI REGIS) | options | 60 | 12 | 51,535 | `99fb580` → `b5be1fe` | 2026-09-13 22:55 |
| 44 | Serezha Calls | crypto | 47 | 15 | 0 | `4a5d6b2` → `408f143` | 2026-09-13 22:55 |
| 51 | Stock Thunder | options | 50 | 16 | 0 | `61f73aa` → `eecf879` | 2026-09-13 23:05 |
| 56 | Stockpro Online | mixed | 51 | 19 | 0 | `452678d` → `9b70b85` | 2026-09-13 22:57 (+ circuit-lock close, uncommitted, see §6) |
| 17 | LIVELONG HARI (SEBI REGIS) | mixed | 19 (live corpus post-cleanup) | 19 | see §6 | this session, see §6 | 2026-09-18 (session, see §6) |

**Attribution caveat, stated honestly:** every commit above is authored as
`Mamatha P`, and each specialist ran in its own git worktree whose branch was
deleted after the merge, so agent session IDs are **not** recoverable for these
seven. What *is* recoverable is the commit + timestamp + subject, which is what the
table records. Live worktrees still on disk, for reference:

| worktree | branch | what it owned | last commit |
|---|---|---|---|
| `.claude/worktrees/agent-a56e1234492c4f19d` | `worktree-agent-a56e1234492c4f19d` | Congress Trades table + profiles (not a parser channel) | 22:25 `618fc0f` |
| `.claude/worktrees/agent-acb68153289210abc` | `worktree-agent-acb68153289210abc` | Super Investors table + profiles (not a parser channel) | 22:14 `a03b4ec` |
| `.claude/worktrees/funny-leavitt-29c1f9` | `claude/funny-leavitt-29c1f9` | `HoldingQuerySet.moves()` N² + slowdown fixes | 21:55 `064183b` |
| `/Users/mamathap/Downloads/worktrees/batch1` | `channel/batch1` | idle at `aece464`, no channel work yet | — |

From here on, an agent **must** write its own row in this table (section 4 contract),
including its worktree path, so attribution stops being reconstructable-after-the-fact.

---

## 2. What is left, and which parts are worth an agent at all

69 channels have no `style_notes`. They are not 69 equal jobs. Bucketed by actual
data in the DB:

| bucket | count | msgs | trades | verdict |
|---|---|---|---|---|
| **A** documented (section 1) | 7 | 357 | 123 | done, revisit only on new message volume |
| **B** parser-blind, ≥30 msgs | 31 | 1,411 | 0 | *candidate* for a specialist — but see §5 first |
| **C** generic parser already yields trades | 24 | 973 | 94 | polish-tier, not specialist-tier |
| **D** sparse or dead (<10 msgs, or last msg before 2026-08-15) | 11 | 177 | 4 | skip, no agent should be spawned |
| **E** near-blind, 16–26 msgs | 3 | 60 | 0 | `50 STOCK MARKET ADDA`, `55 Stockizen Research`, `74 King Of Sensex` — cheap 10-minute pass, not a specialist |

(7 + 31 + 24 + 11 + 3 = 76. Buckets are evaluated in this order, so a stale channel
that happens to have trades lands in D, not C.)

Bucket D, named (do not spawn agents for these): `75 BITCOIN TRADING UP` (7 msgs),
`46 SHAREMARKET HINDI` (6, last 2019-07-28), `76 TRADER WITH SUNIL` (6),
`5 Beat The Street Equity Research` (2), `69 استوکبـاز` (2, last 2022-02-16),
`8 bschart1` (1), `45 Sharekhan` (0), plus stale-but-large `57 Stocktwits India`
(50 msgs, last 2025-11-11), `33 Power Of Stocks` (43, last 2026-07-15),
`42 Sairam Stocks` (42, last 2025-08-05 — duplicate publisher of active `41`),
`13 eu trades` (18, last 2023-04-06).

Bucket B, in descending message count — this is the queue: `7 Bloomberg`, `9 Easy
trading classes`, `12 Equitymaster`, `23 Money creates Money`, `28 No Paid Service
(@Anirbban)`, `31 PL Technical Research`, `34 Priya Yaduvanshiiii`, `47 Short To Mid
Term`, `60 Swing Trader Vishal`, `21 Momentum Bohot Strong Hai`, `25 Mystocks.in`,
`35 ProfitPunch`, `39 Ritvi Taneja (Passionate Trader)`, `65 Trading Ideas By
Darshan`, `20 MarketWolf`, `70 𝐅𝐈𝐍𝐀𝐍𝐂𝐈𝐀𝐋 𝐒𝐀𝐑𝐓𝐇𝐈𝐒`, `38 Richie by Chase Alpha`,
`22 Momentum Trades`, `53 Stockexploderop`, `54 Stockizen Research`, `59 SUPER TRADER
LAKSHYA`, `1 20PAISA..COM`, `63 TheDoji`, `43 Samco`, `64 Theta Gainers`, `62 The
Trading Marvel`, `10 Equiideas V/S (GB)`, `67 TSP Finance`, `11 Equity99`, `29 Nrj
finance`, `73 Crypto Breakout Signals`.

Regenerate any of these lists instead of trusting this snapshot:

```sql
WITH b AS (SELECT c.id, replace(c.short,char(10),' ') nm,
  (SELECT COUNT(*) FROM traderacker_telegrammessage m WHERE m.channel_id=c.id) msgs,
  (SELECT MAX(date(m.ts)) FROM traderacker_telegrammessage m WHERE m.channel_id=c.id) lastm,
  (SELECT COUNT(*) FROM traderacker_trade t WHERE t.channel_id=c.id) tr,
  length(c.style_notes) notes FROM traderacker_channel c)
SELECT id, nm, msgs, lastm, tr FROM b
WHERE notes=0 AND tr=0 AND msgs>=30 AND lastm>='2026-08-15' ORDER BY msgs DESC;
```

---

## 3. Cost protocol — the fixed overhead each agent keeps paying

Measured waste that motivated this section: a full specialist on **Motilal Oswal**
cost ~132k tokens and 6.5 minutes and concluded nothing needed fixing; **NIRMAL
BANG** cost ~307k tokens over ~40 minutes and did land real fixes (§1). Cost
tracks genuine format complexity, not a per-channel rate — so the point of these
rules is to make agents pay the cheap rate until the data proves otherwise.

**Rule 0 — triage before you specialist.** 5 minutes of reading §2 + §5 beats 40
minutes of agent work. A channel that publishes news, not signals, needs a
`style='promo'`-style opt-out, not a parser.

**Rule 1 — do not read `signals.py` end to end.** It is 654 lines; you need one of
six insertion points. Jump straight there:

| you need | where |
|---|---|
| asset-class routing | `classify()` `signals.py:69` |
| the shared regex library | lines `12`–`14` (`NUM`, `SYM` primitives), `93` `RE_CASH`, `97` `RE_OPT`, plus the expiry-token and underscore-strike blocks commented at `95` and `117`–`130`, and the Stockpro lowercase-breakout block at `178`–`201` |
| per-message flow / precedence | `parse_message()` `signals.py:227` — note `RE_EXIT_PRICE*`/`RE_CLOSE_EVENT` span suppression at `243`–`249` |
| profit / exit wording | `RE_PROFIT_POST`/`RE_PROFIT_PRE`/`RE_PIPS` at `476`+, `parse_profit()` `545`, `parse_exit()` `570`, `parse_exit_price()` `584` |
| close-symbol normalisation | `_normalize_close_symbol()` `522` |
| price-less "the run is over" markers | `RE_CIRCUIT_LOCK` + `parse_circuit_lock()` at the end of the file, consumed by `parse_signals`' close path 3 — read that pair before inventing a new close shape |

Read the ~40 lines around your insertion point and the comment blocks; the comments
are the previous agents' KT inline (e.g. why `RE_CASH` is deliberately case-sensitive).

**Rule 2 — never run the 84-test suite by default.** The gate is the `signals.py`
hash above. If your change is confined to one channel's patterns **and** you did not
touch a shared regex, run only your own labels:

```bash
./.venv/bin/python manage.py test traderacker.tests.SignalParserTests.test_options_train_to_range_recap_without_profit_word_is_not_an_exit  # seconds
./.venv/bin/python manage.py test traderacker -v 0    # 29s — ONLY if signals.py's hash differs from the anchor, or you edited a shared RE_*
```

**Rule 3 — never re-parse all 76 channels to check one.** Scope it:

```bash
./.venv/bin/python manage.py parse_signals --channel 39        # one channel
./.venv/bin/python manage.py parse_signals --channel 39 --reclassify
```

A 76-channel pass is justified only when you changed a shared regex, and then the
correct check is a trade-count diff before/after, not eyeballing the dashboard.

**Until §7 is fixed, do not run `parse_signals` unscoped at all.** It is not
idempotent today: every full pass closes one more row in the rupee-stating options
channels and books its profit again. Scope `--channel <id>` even when you changed a
shared regex, and get the cross-channel check from the fingerprint diff in §7's
method instead.

**Rule 4 — batch lookalikes, don't specialize them.** Several queue channels share a
publisher family or house style (e.g. `41`/`42 Sairam Stocks`, `54`/`55 Stockizen
Research`, `48`/`49 Stock Gainers`). One pass over the pair, one commit.

**Rule 5 — record yourself.** In the same commit as your parser change, add your row
to §1, update that channel's `style_notes` to the §4 contract, and append a line to the
§6 run log. Skipping this is what makes the next agent redo your work.

---

## 4. The per-channel KT contract (`Channel.style_notes`)

The seven existing notes are the template; they are what makes a successor agent fast.
Each must contain, in this order:

1. One-paragraph identity: who publishes, at what cadence, which asset classes
   actually appear, and what the channel is *not*.
2. Numbered shapes, each with a **verbatim** message excerpt and which regex path it
   takes (shared vs channel-specific).
3. Traps found the hard way — phrasings that create phantom trades, recaps that are
   not exits, promos that look like signals.
4. What was left deliberately unparsed, and why.
5. `last agent` line: `YYYY-MM-DD HH:MM · <worktree path> · <commit sha>`.

Append your §1 row in the same commit. Test naming convention already in use:
`test_<channel>_<behaviour>` inside `SignalParserTests`
(`test_options_train_safe_can_book_is_not_a_generic_exit`,
`test_crypto_em_dash_long_short`, `test_verb_first_nirmal`).

---

## 5. Known traps in the queue (found by sampling, not by agent runs)

- **Some of bucket B is not parser-blind, it is correctly empty.** Sampled so far (2
  of 31): `7 Bloomberg` is wire headlines ("EXCLUSIVE: TikTok developer ByteDance
  secures a $30 billion loan…") and `12 Equitymaster` is article promos
  ("#EMViewsOnNews - Is NSE IPO Overvalued…") — neither posts entry levels, so zero
  trades is the right answer. The fix is the model's existing opt-out, not a regex:
  `Channel.style` accepts `auto / options / cash / crypto / mixed / promo`, where
  `promo` = "Mostly promo/news (skip)" and `parse_message` short-circuits on it
  (`signals.py:229-232`). Set `style='promo'` + one line of `style_notes` and move on
  — that is a 2-minute resolution for a channel that would otherwise burn a specialist.
  **Sample the other 29 before routing any agent at them.** 30-second sampler:

  ```bash
  sqlite3 -readonly db.sqlite3 "SELECT substr(text,1,300) FROM traderacker_telegrammessage WHERE channel_id=39 ORDER BY mid DESC LIMIT 5;"
  ```

- **Duplicate publishers.** `41`/`42` (Sairam Stocks), `54`/`55` (Stockizen
  Research), `48`/`49` (Stock Gainers) are the same brand on two peers; one of each
  pair is stale. Don't double-spend.
- **Channel 39 Ritvi Taneja (Passionate Trader) — 49 msgs, 0 trades, next in queue.**
  Sampled in the sibling FastAPI project (`/Users/mamathap/Downloads/Telegram/
  telegram-trade-tracker`, `states/-1001871022820.json`) which reads the same message
  corpus. Her house style, already worked out, so start here rather than rediscovering:
  - `"<multi-word ticker> <entry> to <target>"` — `"Adani Ports 1728 to 1785"`,
    `"PPL Pharma 172 to 229++"`, `"Morephan Lab 43 to 122++++"`,
    `"Cpplus 3445 to 3610++"`. `N to M` is the entry→target spine.
  - `"SBIN 1011 / Support 992 / Can hit 1025/1038/1050 / Weak below 992 closing"` —
    support-and-target style, slash-separated targets.
  - Closes are Hinglish prose with **no rupee figure**: `"Jackpot ho gya aaj ka"`,
    `"Booking profit today"`, `"I booked profit."`,
    `"Trailing my stoploss to 210 now."` (that last one moves the SL, it is not a loss).
  - Chatter to keep unparsed: `"Good Morning Guys"`, `"zinga lalaaaaa"`,
    `"Analysing more stocks.\nI'll share soon"`.
  - Realized ₹ must stay blank: she states no rupee amounts, so per the project's
    honesty rule the row is Closed-with-no-₹, never a fabricated figure.
- **`realized` truthfulness.** Only 4 channels currently contribute the ₹53,425 total
  (Options Train ₹51,535, 𝑵𝒂𝒔𝒅𝒂𝒒 masters ₹1,180, NIRMAL BANG ₹689, Angel One ₹20).
  Everything else is either open or states no ₹. A specialist that "improves" a
  channel's realized total without a stated rupee amount is a bug, not a win.

---

## 6. Run log — append one line per agent run, newest first

Format: `YYYY-MM-DD HH:MM · <who/worktree> · <channel id> · <command/change> · <result>`

- **2026-09-18 21:00 · Claude Code session, working tree of `main` · 17 LIVELONG HARI
  (SEBI REGIS) · added "ABV" as an alias for ABOVE/BELOW in the shared
  `RE_ABOVE_BELOW`.** User reported this channel's option-leg trades (CE/PE) were
  closing with no entry price at all. Root cause: this channel's cash-order path
  (`_hari_cash_signal`/`RE_HARI_ENTRY_TRIGGER`) already understood "ABV" as an
  entry-band keyword, but deliberately bails whenever CE/PE appears earlier in the
  message, deferring to `RE_OPT`'s own `RE_ABOVE_BELOW` fallback — which only knew
  the literal words ABOVE/BELOW, not this channel's "BUY abv <price>" abbreviation.
  So every option order using "abv" silently parsed with `entry=None`.
  Fix: `RE_ABOVE_BELOW = r'\b(?:ABOVE|BELOW|ABV)\s*:?\s*[->]?\s*(?:ONLY\s+)?' + NUM`.
  "ABV" was already excluded from ever being misread as a ticker (STOP_WORDS, see
  `_hari_cash_signal`'s own docstring), so it's safe as a keyword alias too.
  Known remaining gap, NOT fixed this pass: the "BUY range <price>" phrasing (e.g.
  HAL 4750 PE) still parses `entry=None` — "RANGE" is too generic an English word to
  safely add to this shared regex without deeper corpus verification; left as a
  documented gap rather than rushed.
  Verified: `traderacker.tests` full suite green (235 tests) before touching the live
  DB. Fingerprint diff (full corpus, copy not live db): diff spans 18 channels, but
  only 4 channels (17, 26, 37, 40) contain the literal string "ABV" in their message
  text at all — the other 14 channels' diff rows are unrelated newly-imported
  messages catching up to already-parsed state, not caused by this regex change
  (confirmed by grep: those channels have zero "ABV" occurrences). Spot-checked all
  4 ABV-containing channels: 17 and 37 gain a correct entry price where they had
  none before (net improvement); 26 (Nirmal Bang)'s "SL ABV <price>" messages are
  unaffected because they never reach the `RE_OPT`/`RE_ABOVE_BELOW` code path at all
  (cash/futures messages, not option-leg); 40's one wrong-looking result
  ("SENSEX 74600 PE 24 SEP 2026" → entry=24, the date's day-number, not the real
  "ABV 440") is a **pre-existing bug, unrelated to this change** — verified via
  `git stash` that the pre-change code produces byte-identical wrong output on the
  same input, so this pass neither caused nor fixed it; out of scope here.
  `signals.py` sha256 after this change: `8f4fe12f98a094a7c4752a6d9c2e965731c779d3af93807199a9c8d9c7f0a0de`.
  Applied live: `parse_signals --channel 17` (after deleting the channel's 27
  corrupted Trade rows + 8 ProcessedProfitEvent rows — unrelated data corruption
  from accidental inline-edits, not a parser bug, see this session's chat log) →
  `3 new · 1 updated`, then a manual dup-cleanup pass deleted 10 stale duplicate
  rows left over from the entry-less first pass. Final state: 19 Trade rows, all
  `manually_edited=False`, closed via `close_eod` with real entry prices and
  intrinsic-value P&L estimates for the options that parsed correctly, `entry=None`
  preserved honestly (no fabricated P&L) for the remaining "range"-phrasing gap.

- **2026-09-14 00:20 · QwenWork session, working tree of `main` (uncommitted) ·
  56 Stockpro Online · added the circuit-lock close path.** `RE_CIRCUIT_LOCK` +
  `parse_circuit_lock()` in `signals.py`, and close path 3 in `parse_signals` which
  reconciles markers *after* the message loop with one close per (channel, symbol).
  Motivation: MOLBIO's 24-Aug call at 1175 was announced over by
  `134613`/`134626` "MOLBIO locked in UPPER CIRCUIT" on 09-10, but the row's entry
  level exists *only* in the 09-11 recap `134640`, so the lock arrives before the
  row does and no inline close can see it; and no rule knew the phrase — `signals.py`
  and all tests had zero references to "circuit".
  Applied: `parse_signals --channel 56` → `2 closed (circuit lock)`;
  `MOLBIO @1175` (id 1505) and `DHOOT @1620` (id 1532) are now `Closed` with
  `realized`/`ltp_exit` **NULL** and `note` carrying the marker mid. `MOLBIO @1690`
  (the later fresh-breakout leg) and `DHOOTTRANS @1620` stay Open — the latter is the
  shorthand-mismatch dup noted at 00:05, still open. Second scoped run: all zero ✓.
  Verification: 84/84 tests; A/B of old vs new code over the *same* input data
  (pre-change `git archive` replayed on the pre-change DB copy) differs on exactly
  those two rows and nothing else across all 76 channels; the 5 corpus prose circuit
  mentions that are not closes (Equity99 "Can Hit Upper Circuit Once Circuit Open",
  Stocky Mind "MOLBIO | 20% upper circuit today", Darshan "Another 10% Upper
  Circuit!", Swing Trader Vishal's lower-circuit posts, Ritvi "20% upper circuit")
  are asserted non-matching in `test_circuit_lock_marker_extraction`.
  Backups: `db.sqlite3.pre-circuit-20260914001605` (then restored, see next entry).

- **2026-09-14 00:18 · QwenWork session · 30 + 51 · found: unscoped `parse_signals`
  is not idempotent (see §7).** A full pass during the verification above closed 8
  rows and pushed realized ₹53,425 → ₹124,465; runs 2/3/4 closed 2, then 1, then 1
  more, reaching ₹210,765 with the row count flat at 221. The old code replayed on
  the same input produced the identical first 8, so this predates the circuit-lock
  change. The live DB was restored from the 00:16 backup and only channel 56
  re-parsed, so the recorded totals are unaffected.

- **2026-09-14 00:05 · QwenWork audit session · 56 Stockpro Online ·
  `parse_signals --channel 56` → `0 new · 0 updated · 0 closed · 0 closed`** —
  idempotent, trade set unchanged at 19 rows / 19 Open / ₹0 realized. `signals.py`
  hash still `86828794368e…`, so no shared grammar moved. DB backed up to
  `db.sqlite3.pre-stockpro-20260914000029` in the QwenWork workspace first (the file
  is gitignored, so it has no other revert path).
  Verdict: **this channel needs no exit-parsing work** — its 51 stored messages
  contain 0 occurrences of `book`/`exit`/`stop`/`TGT` and exactly 1 of `target`, so
  all-Open is the honest state, not a parser miss. Same "nothing to fix" outcome
  Motilal Oswal produced, at a fraction of the cost (scoped query + one parse, no
  specialist).
  **One residual defect, deliberately left open:** `RE_FRESH_BREAKOUT` and
  `RE_SHARED_RESEARCH` (`signals.py:188-201`) capture only the first token of a
  multi-word ticker — documented as intentional shorthand in the comment above them.
  It is cosmetic for `VA TECH WABAG → VA`, `INDO MIM → INDO`, `MAN IND → MAN`, but it
  double-counts when the same call is later restated under an abbreviation variant:
  mid `134648` "DHOOT fresh breakout above 1620" and mid `134676` "✅DHOOTTRANS … it
  looks good above 1620" are both Dhoot Transmission and now sit as two Open trades.
  `PAISALO` at 80.0 and 84.75 is a genuine two-level case, not a dup. Fixing this
  needs an equity alias map (nothing exists — `market.py:20-34` only maps
  index/crypto/commodity/forex roots), which would change `Trade.trade` keys and
  therefore the `uniq_trade_row` constraint → re-parse + full 81-test run, i.e. the
  expensive path. Not worth it until symbol keys feed anywhere user-facing.

---

## 7. Open defect: unscoped `parse_signals` re-books the same profit every run

**Symptom.** Row count stays flat at 221 while `Closed` climbs 32 → 40 → 42 → 45 →
46 and realized climbs ₹53,425 → ₹124,465 → ₹137,865 → ₹186,465 → ₹210,765, one
further close per pass, in channels 30 (Options Train) and 51 (Stock Thunder) only.
Old code on identical input reproduces it, so it is not from the circuit-lock change.

**The tell.** The re-booked amounts are *identical* to a row already closed in the
previous pass, landed on a different leg of the same instrument:

| already closed | next pass also closed | realized on both |
|---|---|---|
| `NIFTY 23650 PE @ 190` | `NIFTY 23650 PE @ 165` | ₹24,300 |
| `SENSEX 74100 CE @ 560` | `SENSEX 76100 CE @ 500` | ₹13,400 |

A recap's rupee figure is therefore attributed again each time, to whatever row is
next in line.

**Suspected mechanism.** `parse_signals.py:224-237`: when a message states a profit
and touched nothing, the fallback tokenises the whole message and takes
`cand.filter(trade__icontains=w).order_by('-date').first()` over *all* Open trades in
the channel. `icontains` on a token like `NIFTY`/`SENSEX` matches every option leg of
that index, so once the intended row is Closed the same figure lands on its neighbour,
and `book()` then closes it on the trailing/exit wording. Nothing records that a given
message's profit has already been consumed, so the next run repeats the walk.

**Reproduce safely (never against `db.sqlite3` directly):**

```bash
git archive HEAD | tar -x -C /tmp/repro && cp db.sqlite3 /tmp/repro/db.sqlite3
cd /tmp/repro && for i in 1 2 3; do /path/to/.venv/bin/python manage.py parse_signals | tail -1; done
```

**Regression check to use instead of a full parse** — a grouped fingerprint diff
before/after, per channel, which is what proved the circuit-lock change clean:

```bash
sqlite3 -readonly -separator '|' db.sqlite3 "SELECT channel_id,status,trade,COALESCE(entry,-1),COALESCE(realized,-999),COUNT(*) FROM traderacker_trade GROUP BY 1,2,3,4,5;" > /tmp/fp.txt
```

**What a fix must guarantee.** A stated profit is consumed at most once per
(channel, message mid); the fallback must match the *stated* instrument rather than a
substring of the message, and only against a trade whose date is not after the
booking message; and two consecutive unscoped runs must produce byte-identical
fingerprints. Until then treat any realized total above ₹53,425 as suspect, and note
the leaderboard/accuracy scores read these rows, so this is not cosmetic.

**RESOLVED.** Verified via the exact reproduction steps above: two, then three,
consecutive unscoped runs now produce byte-identical fingerprints (7,519 rows, 0
row-count drift, 0 closed-count drift on every pass after the first).

The root cause was broader than the original diagnosis — three separate issues,
found by actually tracing one specific misattributed row (`DIVISLAB` in channel 3)
message-by-message rather than reasoning about the fallback in the abstract:

1. **Substring matching** (as diagnosed above) — fixed by requiring the trade's FULL
   symbol string to appear verbatim in the message, not a loose single-word token.
2. **`peak_profit` treated as persisted state instead of derived state** — a second
   run started from the first run's *final* (highest) peak, so an early/lower-profit
   message immediately looked like a trailing-stop breach against a peak the trade
   hadn't actually reached yet in that pass. Fixed by resetting `peak_profit` to NULL
   for the run's scope before replaying.
3. **The real long-tail cause**: a profit/exit message whose own timestamp precedes
   its target trade's entry message (a genuine pattern in the data — e.g. a stale
   "booked @ price" post that's actually about an earlier, already-closed position)
   correctly finds no candidate on a run starting from an empty `Trade` table. But
   since `parse_signals` is normally re-run WITHOUT clearing `Trade` first, a second
   run finds that some *other*, unrelated trade — created later in the first run's
   replay — now happens to be sitting Open, and wrongly attaches the stale message to
   it. `ORDER BY ts` alone was also not a fully deterministic replay order (2,510+
   groups of messages share an identical timestamp, up to 23 at once), which
   compounded this. Fixed by (a) adding `mid` as a secondary sort key so the replay
   order is fully deterministic, and (b) a new model, `ProcessedProfitEvent`
   (`channel`, `mid`, `kind` — 'profit' or 'exit_price'), that durably records every
   profit/exit message *considered* — on a miss as well as a hit — so a later run
   skips it outright instead of re-evaluating it against a `Trade` table that has
   since changed. This is independent of any `Trade` row, so it survives the
   duplicate-merge path deleting the row that was originally touched.

See `traderacker/management/commands/parse_signals.py` and the `ProcessedProfitEvent`
model in `traderacker/models.py` for the implementation.

---

## 8. Batch8 final wrap-up (2026-09-15)

**Assignment:** the 7 lowest-volume channels not yet covered by a specialist pass —
`67 TSP Finance`, `78 Chart Wallah`, `18 Market Maestro`, `15 Index trading with CA
Nitin Murarka (SMC)`, `53 Stockexploderop`, `50 STOCK MARKET ADDA`, `5 Beat The
Street Equity Research Reports | Books`. Worktree
`/Users/mamathap/Downloads/worktrees/batch8`, commit `8ab3d97` (see git log for the
final commit sha if this doc update lands separately).

**Result, per channel:**

| channel | style | msgs | trades after | note |
|---|---|---|---|---|
| 67 TSP Finance | promo | 723 | 0 | pure news/commentary; removed 2 phantom trades the generic parser had minted from stray prose |
| 78 Chart Wallah | promo | 713 | 0 | analyst/research chatter, target-price call-outs, no entry+SL calls |
| 18 Market Maestro | auto | 698 | 59 | already correctly parsed via the generic option path; verified its "TODAY LIVE PROFIT...ACCOUNT HANDLING" scam ad does NOT false-positive as a profit event |
| 15 Index trading with CA Nitin Murarka (SMC) | options | 696 | 77 (was 29) | **bug fixed**: `RE_SMS_RANGE_ENTRY` didn't tolerate the emoji arrow in "ONLY IN RANGE 👉 <price>", so the channel's dominant entry shape produced 0 trades under the old regex despite its header already matching. Widened; verified channel-agnostic-safe (all 45 corpus-wide behavior diffs land on channel 15 only) |
| 53 Stockexploderop | promo | 687 | 0 | product-promo chatter ("swingalgo"), stop-loss/target words only ever used in retrospective narrative, never as an actionable call |
| 50 STOCK MARKET ADDA | promo | 399 | 0 | IPO/news/GST-data feed; "SL OF ₹X" phrasing is a passive listing-day hold suggestion, not a trade signal |
| 5 Beat The Street Equity Research Reports \| Books | promo | 231 | 0 | research-report/PDF distribution + broker target-price call-outs, not entry signals |

**Batched verification (full 82-channel corpus, `Trade` + `ProcessedProfitEvent`
cleared first, per the §7-fixed idempotent `parse_signals`):**

- `manage.py test traderacker` — 176/176 passing (175 pre-existing + 1 new:
  `test_index_trading_nitin_range_arrow_entry`).
- Full unscoped `parse_signals`: `12699 new · 125 updated · 1128 closed (exit/trailing)
  · 1304 closed (exit price)`. Per-channel trade-count diff before/after across all 82
  channels: **only channels 15 (29 → 77) and 67 (2 → 0) changed** — exactly the two
  channels this batch touched, zero regression elsewhere.
- Second unscoped run (no clearing): `0 new · 0 updated · 0 closed (exit/trailing) ·
  0 closed (exit price)` — idempotency holds, confirming §7 stays resolved.
- `manage.py check` — clean (only the pre-existing `STATICFILES_DIRS` warning,
  unrelated).
- Spot-checked sample `Trade` rows for 15 and 18 against source message text — entries
  match; blank-entry rows are honest gaps (headers with no price ever stated in that
  message), not fabrications.

**Final totals across all 82 channels (post this batch):** 12,699 `Trade` rows, 2,432
Closed, ₹18,080,523 aggregate `realized` (inherited pre-existing state from many
previously-specialized rupee-stating channels — not something this batch changed or
audited; §7's specific double-booking defect is independently confirmed still resolved
via the idempotency check above).

**Correction to this batch's own assignment brief — read before treating "final
batch" as accurate:** the brief this agent was given asserted that after this batch
"all channels with meaningful message volume will have had a dedicated specialist
pass." **That is not true of the live DB.** A fresh query at the end of this batch
(`SELECT ... WHERE length(style_notes)=0 ORDER BY msgs DESC`) shows 8 channels with
**369–2,318** messages — an order of magnitude above the "meaningful volume" bar —
still carrying zero `style_notes`, i.e. never touched by any specialist despite being
well above the size of several channels this and prior batches did cover:

| id | channel | msgs |
|---|---|---|
| 37 | RAJESH PALVIYA | 2,318 |
| 12 | Equitymaster | 2,011 |
| 7 | Bloomberg | 1,996 |
| 31 | PL Technical Research | 1,978 |
| 28 | No Paid Service (@Anirbban) | 1,965 |
| 9 | Easy trading classes | 1,935 |
| 23 | Money creates Money | 1,905 |
| 34 | Priya Yaduvanshiiii | 369 |

Two of these (`7 Bloomberg`, `12 Equitymaster`) were already sampled and diagnosed as
pure wire-news/promo back in §5 of this same doc — the conclusion was reached, but
`style='promo'` was apparently never actually committed for them, so they still parse
under `'auto'` today. The other six were never sampled at all as far as this doc
records. **A future batch should triage these 8 before declaring the corpus done** —
this wrap-up deliberately does not claim they're covered, since the DB itself
contradicts that.

**Channels genuinely left untouched by design** (below the ~80-message bar, `style_notes`
empty, real skip candidates): `36 PTS PRABHAT TRADING` (78), `42 Sairam Stocks` (73,
duplicate publisher of active `41`), `73 Crypto Breakout Signals` (30), `13 eu trades`
(18), `74 King Of Sensex` (18), `75 BITCOIN TRADING UP STOCK` (7), `46 SHAREMARKET
HINDI` (6), `76 TRADER WITH SUNIL` (6), `69 استوکبـاز` (2), `8 bschart1` (1), `45
Sharekhan` (0).

last agent: 2026-09-15 · `/Users/mamathap/Downloads/worktrees/batch8` · see git log
for commit sha

