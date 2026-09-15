# Sets Channel.style / style_notes for the 8 channels covered by the
# "batch2" full-history specialist pass (docs/AGENT_HANDOFF.md pattern):
# Ashika Calls, MarketWolf - Stocks & Options, Stocktwits India,
# Short To Mid Term(R)(TM), THEBULLOPTIONS, Swing Trader Vishal,
# Stocky Mind, Momentum Bohot Strong Hai. Data-only migration — safely
# no-ops if a channel doesn't exist yet (fresh/test DB), and is idempotent
# (re-running it just overwrites with the same values).
from django.db import migrations

ASHIKA_CALLS = (
    "Ashika Group's official broker research desk (Ashika Stock Broking) — "
    "clean, machine-generated, high-volume (1956 tracked messages). Posts "
    "cash-equity, futures and options intraday/positional calls, mixed "
    "with app-feature announcements, bond/OFS promos and retrospective "
    "\"delivery update\" performance recaps.\n\n"
    "DOMINANT SHAPES (98.9% coverage on the full 1956-message history, up "
    "from ~69% before this pass — 568 of 603 previously-unparsed messages "
    "used shape 1 alone):\n"
    "1. \"BUY <SYM> [CASH|FUT|FUTURES]? [(<expiry>)]? CMP <price[-range]> "
    "SL <sl> TGT <tgt>\", e.g. \"BUY TCS FUT (30 DEC)CMP 3100 SL 3010 TGT "
    "3240\", \"BUY LT CMP 3850-3857 SL 3740 TGT 4035\", \"BUY NIFTY 22500 "
    "CE (27 MAR) CMP 250-290 SL 150 TGT 780\". The \"(<expiry>)\" "
    "parenthetical between the symbol/FUT keyword (or CE/PE strike) and "
    "CMP is this channel's signature quirk — RE_VERB_FIRST/RE_OPT have no "
    "room for it by default, so it silently dropped the CMP price "
    "entirely. Fixed via RE_VERB_FIRST_ASHIKA (cash/futures) and the "
    "RE_OPT_PAREN_CMP fallback (options), both style-gated to 'mixed'.\n"
    "2. Ticker \"LT\" (Larsen & Toubro) is 2 characters, one short of the "
    "shared SYM pattern's 3-char floor — special-cased by literal name in "
    "RE_VERB_FIRST_ASHIKA's SYM_ASHIKA rather than lowering that floor "
    "globally (which would open the door to ordinary two-letter English "
    "words like \"TO\" becoming phantom tickers elsewhere). Because this "
    "is style-gated to 'mixed' rather than to this one channel, it also "
    "fires for Angel One Research's own \"BUY LT 1 shares at 3495.00.\" "
    "broker-order posts (same real ticker) — a verified-correct side "
    "effect (six previously-invisible LT positions there now parse "
    "correctly, entry/SL/TGT matching the stated values exactly), not a "
    "regression; confirmed via a full old-vs-new parse diff that it is "
    "the ONLY thing this migration changes in Angel One's history.\n"
    "3. Lower/mixed-case index option names, e.g. \"BUY Nifty  25500 PE "
    "(JAN20) CMP 64 to 62  SL 35 TGT 100\" — RE_OPT's root is upper-case "
    "only by design; caught by the new RE_OPT_INDEX_CI (restricted to the "
    "known index-root names, style-gated to 'mixed').\n"
    "4. Close-outs use \"BOOK [PARTIAL] PROFIT IN <SYM> CMP <price>\" (564 "
    "occurrences) — RE_CLOSE_EVENT previously only accepted \"AT\"/\"@\" "
    "as the price marker (Nirmal Bang Official's phrasing); extended "
    "(ungated — parse_exit_price() has no style parameter, and a "
    "full-corpus grep across all 82 channels found the \"CMP\" variant "
    "only here and in Samco channel 43, both always a genuine close, never "
    "a false positive) to also accept \"CMP\".\n\n"
    "TRAPS / DELIBERATELY LEFT UNPARSED (the remaining ~1% — 21 of 1956 "
    "messages): 8 \"ASHIKA INSIGHT DELIVERY UPDATE ... TARGET "
    "ARCHIEVED/ACHIEVED\" retrospective recaps (no BUY/SL/TGT wording this "
    "codebase's exit machinery can act on, and always positively "
    "resolved — low value to chase); promo (new-brand announcement, "
    "Dhanush app-feature blasts, OFS/webinar posts); one \"IGNORE CALL IN "
    "SAIL...AS IT IS IN BAN PERIOD\" (explicitly says not to take it — "
    "correct to skip); a couple of one-off source typos (\"BUY TITAN FUT "
    "FUT (JAN26)...\" double keyword, \"BUY APOLLOHOSP FFUT (MAY26)...\" "
    "misspelled FUT); one \"BUY NiftyBank ...\" alias (channel almost "
    "always writes \"NIFTY\"/\"BANKNIFTY\", this is a single one-off "
    "variant); and \"BUY HDFC LIFE FUT...\" (a genuine multi-word cash "
    "symbol this file's single-token SYM convention doesn't capture).\n\n"
    "last agent: 2026-09-14 · /Users/mamathap/Downloads/worktrees/batch2 "
    "(channel/batch2) · batch2 specialist pass"
)

MARKETWOLF = (
    "MarketWolf - Stocks & Options: a paid-tip broker template channel "
    "(index/commodity/stock options only) that publishes EVERY call from "
    "the same three-line structured template — 1960 tracked messages, "
    "722 (36.8%) use the structured entry shape below; the remainder is "
    "daily commentary (\"Hunting Zones\", \"Post Market Update\", Gift "
    "Nifty gap notes) and promo, correctly left unparsed.\n\n"
    "ENTRY SHAPE (previously 0 of 1960 parsed — the channel had ZERO "
    "trades before this pass): \"Trade SENSEX @11,400 only!\\n\\nIndex : "
    "SENSEX\\n\\nOPTION:\\xa0 77400 CALL (CE) 30th APR\\n\\n\U0001F3F9 BUY "
    ": 540-570\\n\\n\U0001F3AF Target & Stop Loss : RA Team To Update ...\" "
    "— THE TRAP: the \"@11,400\" on line 1 is the SUBSCRIPTION PRICE for "
    "the paid tip service, NOT a trade price; a naive \"SYMBOL @ PRICE\" "
    "regex would misread it as the option premium. The REAL entry is the "
    "first number of the \"BUY : <low>-<high>\" range three lines later, "
    "after an \"Index\"/\"Commodity\"/\"Stock\" line naming the underlying "
    "and an \"OPTION: <strike> CALL|PUT (CE|PE) <expiry>\" line giving the "
    "actual leg. Parsed by RE_MARKETWOLF_OPTION, style-gated to "
    "'options'. Target/stop-loss are deliberately never given publicly "
    "(\"RA Team To Update\" is the channel's own paywall placeholder, not "
    "a real value) — target/stop_loss are left blank rather than "
    "fabricated.\n\n"
    "CLOSE-OUTS ARE DELIBERATELY LEFT UNPARSED: \"Trade SENSEX @Rs "
    "11,375 only!\\n\\U0001F3AF Target Hit\\n\\nInstrument: NIFTY\\n"
    "Status: Target Achieved ✅\", \"GOLD MINI at ₹6,000 | SL "
    "Triggered\\n\\nInstrument: GOLD MINI\\nStatus: -20% Loss\" — these "
    "give NO price and NO strike, only an underlying name and a status/%"
    " figure, and the same underlying can have multiple concurrently-open "
    "legs, so there is no confident way to attribute the close to the "
    "correct specific leg (\"no confident match -> no trade\").\n\n"
    "last agent: 2026-09-14 · /Users/mamathap/Downloads/worktrees/batch2 "
    "(channel/batch2) · batch2 specialist pass"
)

STOCKTWITS_INDIA = (
    "Stocktwits India: the official Stocktwits India news/social feed — "
    "headlines, in-app polls (\"Vote now in the Stocktwits POLL\"), "
    "trending-symbol digests, IPO calendar notices, and links to "
    "third-party SEBI-RA analyst posts hosted on stocktwits.com. Sampled "
    "the full 1978-message tracked history: zero messages state an actual "
    "entry price, SL or target — even messages that reference \"targets\" "
    "or \"SEBI RA\" only link out to an external post rather than quoting "
    "a level in-channel. Not a signal channel at all. style='promo' — "
    "correctly reduces the single pre-existing phantom-ish 0-trade state "
    "to a clean, honest zero.\n\n"
    "last agent: 2026-09-14 · /Users/mamathap/Downloads/worktrees/batch2 "
    "(channel/batch2) · batch2 specialist pass"
)

SHORT_TO_MID_TERM = (
    "Short To Mid Term®™: Hinglish retail cash-equity swing/"
    "positional channel, cross-posted from Twitter/X, hashtag-ticker "
    "convention (\"#IOC\", \"#CENTUM\"). 1971 tracked messages; only 33 "
    "produced a signal before this pass (1.7% coverage) despite two clear "
    "dominant shapes covering 1938 of them.\n\n"
    "SHAPE A — forward entry call (869 messages): \"\U0001F195⬇️"
    "\U0001F4E2\\n\\n\U0001F4B9  CENTUM ELECTRONICS\\n\\n\U0001F387  CMP-  "
    "1210-1212\\n\\n\U0001F3A0 UPSIDE RESISTANCE  - 1260-1310-1370-1450-"
    "1550\\n\\n#CENTUM\\n\\n\U0001F4A5 DISCLAIMER...\". The SYMBOL is taken "
    "from the trailing HASHTAG (#CENTUM), not the display name before it "
    "(\"CENTUM ELECTRONICS\" or, worse, \"NYKAA - FSN E-COMMERCE VENTURES "
    "Ltd.\" whose hashtag is the unrelated-looking \"#NAYAKA\") — the "
    "hashtag is this channel's own canonical short ticker and the display "
    "name is not reliably parseable. CMP's first number is entry, the "
    "resistance ladder's first number is target (this file's usual "
    "single-value ladder convention). Parsed by RE_STMT_ENTRY, style-gated "
    "to 'cash'.\n\n"
    "SHAPE B — retrospective \"called it\" recap (1222 messages, "
    "overlapping some with shape A's channel-agnostic risk): \"#IOC 94 TO "
    "145+\U0001F680\U0001F680\U0001F680   3RD TGT DONE ✅✅\", "
    "\"#CGPOWER 510-511 TO 541+ FIRST TGT DONE...\". States BOTH the entry "
    "and the already-hit exit level in one line. Parsed by RE_STMT_RECAP "
    "as an Open trade with entry/target filled (style-gated to 'cash').\n"
    "KNOWN, DELIBERATE LIMITATION on shape B: despite \"TGT DONE\"/"
    "\"REACHED\" wording confirming the position is already closed, it is "
    "recorded Open, not Closed. parse_signals.py's exit-PRICE path "
    "evaluates BEFORE this same message's signal has created the Trade "
    "row (unlike its profit-booking path, which runs after), so a "
    "same-message create-and-close can never actually close here — and, "
    "once the message is marked processed, never will on any later run "
    "either. Fabricating a Closed/realized status this codebase's current "
    "command structure can't actually derive would violate the "
    "realized-truthfulness rule far more than an accurate-but-stale Open "
    "row. Left as a documented gap rather than touching "
    "parse_signals.py.\n\n"
    "ALSO CAUGHT: \"#SWANENERGY 708 T0 754\" (one-off \"T0\" zero-for-O "
    "typo), stylized-Unicode-bold \"\U0001D652\U0001D643\U0001D608\U0001D61B "
    "\U0001D652\U0001D611\U0001D617\U0001D608\U0001D5FF\U0001D5F8...\" "
    "renderings of \"WHAT UPSIDE PATTERN...\" (~25 messages use "
    "mathematical-alphanumeric Unicode instead of plain ASCII letters — "
    "genuinely invisible to any ASCII keyword match) and bare Twitter "
    "links with no accompanying text are deliberately left unparsed "
    "(long-tail, ~2-3% of the corpus each).\n\n"
    "last agent: 2026-09-14 · /Users/mamathap/Downloads/worktrees/batch2 "
    "(channel/batch2) · batch2 specialist pass"
)

THEBULLOPTIONS = (
    "THEBULLOPTIONS: a SENSEX-options-only tip channel with an unusual "
    "posting pattern — the SAME option leg is reposted dozens of times "
    "through the trading day as a running LTP ticker, e.g. (2000 tracked "
    "messages total) \"\U0001F4CA SENSEX 74000 PE (04 JUN)\\n\\n\U0001F4C8 "
    "BUY ABOVE 370\\n\\n\U0001F3AF TARGET PREMIUM\\n\\n☠️SL - "
    "PREMIUM\" (the genuine entry trigger, once per leg), then ~20-30 "
    "bare-number reposts of the SAME leg (\"...\\n375\", \"...\\n380\", "
    "..., \"...\\n485\") as the premium moves, interspersed with "
    "milestone placeholders (\"Active ✅\", \"FIRST TARGET DONE "
    "✅\", \"BOOM \U0001F525\U0001F680\U0001F4C8\", \"100 POINT "
    "JACKPOT DONE ✅\") and a final prose recap (\"Boom 370 To 485 = "
    "115+ Point big Jackpot\U0001F525\").\n\n"
    "THE TRAP: RE_OPT already matched the option leg (\"SENSEX 74000 "
    "PE\") on every single repost before this pass, but its premium group "
    "can't reach past the \"(<expiry>)\" parenthetical, so ALL 63 "
    "pre-existing trades in this channel had entry=NULL. The naive fix — "
    "grab whatever number follows the parenthetical on every message — "
    "would have created a SEPARATE phantom Trade row for every single "
    "repost (370, 375, 380, ... are all different \"entry\" values under "
    "the (channel, trade, entry) upsert key), exploding 2000 messages "
    "into ~2000 rows instead of ~85 real calls. Fixed correctly by only "
    "filling entry when the message contains the genuine \"BUY "
    "ABOVE/BELOW <price>\" trigger phrase (searched across the FULL "
    "remainder of the message, not a small window, since it can sit "
    "several lines past the parenthetical) — every other repost keeps "
    "entry=None and collapses harmlessly into the same (channel, trade, "
    "None) row instead of minting a new one. Style-gated to 'options'; "
    "verified this changes zero parsed signals for either other "
    "'options'-style channel (Options Train, Stock Thunder) or "
    "MarketWolf (also 'options').\n\n"
    "DELIBERATELY LEFT UNPARSED: the milestone/recap messages (\"FIRST "
    "TARGET DONE\", \"Boom 370 To 485 = 115+ Point big Jackpot\") never "
    "state a rupee profit or give a confidently-attributable exit price "
    "in this codebase's supported shapes, so every leg here stays Open "
    "rather than a guessed Closed status — same honesty rule as the "
    "MarketWolf note above.\n\n"
    "last agent: 2026-09-14 · /Users/mamathap/Downloads/worktrees/batch2 "
    "(channel/batch2) · batch2 specialist pass"
)

SWING_TRADER_VISHAL = (
    "⚡️Swing Trader Vishal \U0001F1EE\U0001F1F3: an individual "
    "trader's Hinglish swing-trade journal, cross-posted from Twitter/X, "
    "hashtag-ticker convention (often lower/mixed case, e.g. \"#tanla\", "
    "\"#tatacomm\"). 1987 tracked messages; genuinely low signal density — "
    "most of the channel is \"Premium Members\" upsell teasers, chart "
    "screenshots with no stated price, trader-mindset Hinglish "
    "commentary, and IPO watchlist posts with no entry level.\n\n"
    "DOMINANT PARSEABLE SHAPE (70 of 1987 messages): \"Bought #<SYM> "
    "<PRICE>\", e.g. \"Bought #BFUTILITIE 810\", \"Bought #Vascon 63.8\", "
    "\"Bought #tatacomm @ 1946\". Parsed by RE_VISHAL_BOUGHT (ticker "
    "uppercased from whatever case the hashtag used), style-gated to "
    "'cash'.\n\n"
    "DELIBERATELY LEFT UNPARSED (long-tail, low volume individually): "
    "\"Exited #SYM [at] PRICE\" close-outs (0 with both a symbol and a "
    "confident price in the sampled corpus — most just say \"Exited "
    "#DYCL ❗\" or \"EXITED at SL ❗\" with no number); \"#SYM N "
    "To M\" recap shape (~7 messages, e.g. \"#RPTECH 323 To 333\"); "
    "\"#SYM ... above/below N\" watch-level posts (~7 messages, e.g. "
    "\"Watch this stock above 81 it can blast\") — none of these clear "
    "a volume bar that would justify their own regex given this "
    "channel's fundamentally low, noisy signal density.\n\n"
    "last agent: 2026-09-14 · /Users/mamathap/Downloads/worktrees/batch2 "
    "(channel/batch2) · batch2 specialist pass"
)

STOCKY_MIND = (
    "Stocky Mind: a trader-mindset/journal channel (\"Day - N\" daily "
    "quotes, \"#StockyMindset\" reflections, mentorship promo) with "
    "occasional trade recaps in informal prose. 1954 tracked messages; "
    "genuinely low structured-signal density — trades are mentioned as "
    "narrative asides, not systematic entry alerts.\n\n"
    "DOMINANT PARSEABLE SHAPE (87 of 1954 messages): \"⚡️ "
    "<SYM> ... <entry> to <exit>\", e.g. \"⚡️ CRUDEOIL\\n\\n9085 "
    "to 8920 | 5R+\\n\\nLocked the majority gains\", \"⚡️ "
    "APOLLOPIPE | Swing Trade\\n\\n429 to 454+ \U0001F4A5 | 6%+\". "
    "Direction is inferred from which side of the range is higher (a "
    "down-move recap like the CRUDEOIL example above is a SELL), same "
    "convention as the bare-crypto-prose fallback elsewhere in this "
    "file. Parsed by RE_STOCKY_RECAP, style-gated to 'mixed' (the "
    "channel trades both stocks and commodities — CRUDEOIL/SILVER are "
    "already in this file's COMMODITY/METALS sets, so classify() "
    "auto-detects the asset class correctly without any extra work).\n\n"
    "DELIBERATELY LEFT UNPARSED: informal entries with no clean numeric "
    "pair (\"Entered near 1544 with just 5 points SL\", \"Added 176 with "
    "1 point SL\") and the \"Entry: N | SL: N\" labeled-but-standalone "
    "format (only 3 occurrences) — too low-volume and too varied in "
    "phrasing to justify a dedicated regex; the vast majority of the "
    "channel (>80%) is genuinely price-free mindset/promo content where "
    "zero signal is the honest answer.\n\n"
    "last agent: 2026-09-14 · /Users/mamathap/Downloads/worktrees/batch2 "
    "(channel/batch2) · batch2 specialist pass"
)

MOMENTUM_BOHOT_STRONG_HAI = (
    "Momentum Bohot Strong Hai \U0001F4AA (MBSH): a mentorship-community "
    "engagement channel — daily Hinglish check-in prompts (\"Kya haal "
    "chal dosto?\", \"How much % did your portfolio react today?\"), "
    "earnings-calendar digests, mentorship-enrollment promo (\"30% Off "
    "Coupon Code...DM - @dhawaljainmbsh\"), and bare watchlist mentions "
    "(\"#SJS | How Is This Setup? | High RS Stock\", \"#ADVAIT | One More "
    "Retest Setup | Keep In Radar\") that never state an entry price, SL "
    "or target. Sampled the full 1951-message tracked history: zero "
    "genuine trade signals with a stated price. The single pre-existing "
    "Trade row (\"MAY\" @ entry 1.0) was a phantom match against an "
    "earnings-calendar date line (\"May 13, Wednesday - Today\"), not a "
    "real call. style='promo' — correctly eliminates that phantom and "
    "reflects the channel's actual content honestly.\n\n"
    "last agent: 2026-09-14 · /Users/mamathap/Downloads/worktrees/batch2 "
    "(channel/batch2) · batch2 specialist pass"
)


def set_styles(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    updates = [
        ('Ashika Calls', 'mixed', ASHIKA_CALLS),
        ('MarketWolf - Stocks & Options', 'options', MARKETWOLF),
        ('Stocktwits India \U0001F1EE\U0001F1F3', 'promo', STOCKTWITS_INDIA),
        ('Short To Mid Term®™ \U0001F680', 'cash', SHORT_TO_MID_TERM),
        ('THEBULLOPTIONS', 'options', THEBULLOPTIONS),
        ('⚡️Swing Trader Vishal \U0001F1EE\U0001F1F3', 'cash', SWING_TRADER_VISHAL),
        ('Stocky Mind', 'mixed', STOCKY_MIND),
        ('Momentum Bohot Strong Hai \U0001F4AA', 'promo', MOMENTUM_BOHOT_STRONG_HAI),
    ]
    for name, style, notes in updates:
        Channel.objects.filter(name=name).update(style=style, style_notes=notes)


def unset_styles(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    names = [
        'Ashika Calls',
        'MarketWolf - Stocks & Options',
        'Stocktwits India \U0001F1EE\U0001F1F3',
        'Short To Mid Term®™ \U0001F680',
        'THEBULLOPTIONS',
        '⚡️Swing Trader Vishal \U0001F1EE\U0001F1F3',
        'Stocky Mind',
        'Momentum Bohot Strong Hai \U0001F4AA',
    ]
    Channel.objects.filter(name__in=names).update(style='auto', style_notes='')


class Migration(migrations.Migration):

    dependencies = [
        ('traderacker', '0017_processedprofitevent'),
    ]

    operations = [
        migrations.RunPython(set_styles, unset_styles),
    ]
