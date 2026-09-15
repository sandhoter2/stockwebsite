# Sets Channel.style / style_notes for the 8 channels covered by the
# "batch6" full-history specialist pass (docs/AGENT_HANDOFF.md pattern):
# Equity99, Momentum Trades, Bharath's Market Research (SEBI Registered),
# MARKET MASTER HUB, STOCK MARKET SCHOOL, @kuttrapali26, The Trading
# Marvel, Power Of Stocks. Data-only migration — safely no-ops if a
# channel doesn't exist yet (fresh/test DB), and is idempotent (re-running
# it just overwrites with the same values).
from django.db import migrations

EQUITY99 = (
    "Equity99 (channel 11) -- a stock-tips/promo channel: news-wire "
    "macro digests (\"Morning Alert..\"), and a recurring \"pick of the "
    "day\" format under headers like \"Special Situation Stock\"/\"Special "
    "day pick\"/\"Investment Pick\"/\"Game Changer\".\n\n"
    "DOMINANT SHAPE: the company name sits alone on its own line, "
    "immediately followed by \"Cmp\"/\"CMP\"/\"At\" and the current price "
    "(\"Rudra Global Infra Cmp 24\", \"Univastu India Cmp 127\", "
    "optionally with a BSE scrip code in between: \"Rudra Global Infra "
    "BSE Code 539226 At 37\"), then a paragraph or two later, \"Test "
    "Resistance <n1> / <n2> [/ <n3>...]\" (first number kept as target, "
    "same never-average-a-ladder convention as elsewhere in this file) "
    "and often \"Sl <price>\" a few lines after that (already read "
    "generically by the existing message-level RE_SUPPORT fallback -- no "
    "new code needed for SL). New RE_EQUITY99_ENTRY/RE_EQUITY99_TARGET + "
    "_equity99_special_signal in signals.py, style-gated to 'cash' (set "
    "here). Only 3 of 1700 tracked messages produced a trade before this "
    "pass (all 3 were phantoms, see TRAPS); now ~37.\n\n"
    "TRAPS FOUND THE HARD WAY:\n"
    "1. The entry regex's own required \"Cmp\"/\"At\" keyword is only "
    "case-insensitive for \"Cmp\" (also matches \"CMP\") -- \"At\" stays "
    "case-SENSITIVE. Making \"At\" case-insensitive too was tried and "
    "reverted: it matches the word \"at\" incidentally in ordinary prose "
    "across dozens of other channels (\"BUY HINDCOPPER... AT 55\", \"NET "
    "PROFIT... AT...\") -- checked empirically before rejecting that gate.\n"
    "2. The entry regex REQUIRES \"Test Resistance\" to co-occur in the "
    "SAME message -- without that anchor, the bare \"<Words> At/Cmp "
    "<price>\" shape alone is a large false-positive surface (matches "
    "results-digest prose like \"NET PROFIT AT...\"/\"GROSS NPA...\" in "
    "several 'mixed' channels). Requiring \"Test Resistance\" narrows "
    "this to 0 matches on every OTHER channel across the full 82-channel "
    "corpus -- verified this shape is unique to Equity99.\n"
    "3. A redundant \"<Symbol> At CMP <price>\" double-marker (one real "
    "message: \"Tejas network At CMP 422\") doesn't match at all -- "
    "correctly dropped rather than mis-parsed (the word \"At\" is itself "
    "excluded from the symbol capture via negative lookahead, which then "
    "leaves nothing to satisfy the trailing Cmp/At requirement when BOTH "
    "words are present back-to-back). Single occurrence in the tracked "
    "corpus; not worth chasing further.\n"
    "4. \"Special Situation Stock\"/\"Investment Pick\"/etc. header words "
    "never leak into the symbol capture because the regex requires the "
    "symbol to sit on the SAME line as \"Cmp\"/\"At\" -- header lines are "
    "always separated by a blank line.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch6 "
    "· see git log for commit sha"
)

MOMENTUM_TRADES = (
    "Momentum Trades (channel 22) -- a personality-led swing-trading "
    "channel: mostly sarcastic Hinglish banter, market commentary, and "
    "quote/meme posts, with a genuine one-shot entry->target call sitting "
    "in single terse lines here and there.\n\n"
    "DOMINANT REAL SHAPE: a single capitalized word (the ticker, first "
    "letter upper-case, no other case constraint) directly followed by "
    "\"N to M\" on the SAME line -- \"Graphite 604 to 617\", \"Skipper 560 "
    "to 577\", \"Ifci 82 to 87\", \"Kei 4741 to 4900\" -- or the symbol "
    "alone on its own line with the price pair on the next (\"Aeroflex"
    "\\n\\n470 to 511\"). New RE_MOMENTUM_SAMELINE/RE_MOMENTUM_NEXTLINE + "
    "_momentum_word_to_word_signal, style-gated to 'cash' (set here). "
    "0 -> 6 trades on the tracked history.\n\n"
    "TRAPS: this channel constantly reposts the SAME running position's "
    "current level with NO symbol restated (\"813 to 845\", then \"813 to "
    "870\", then \"813 to 900\"...) -- these never match at all since "
    "there's no capitalized word to anchor on, which is the desired "
    "behavior (re-parsing every update as a fresh trade would be a "
    "phantom-duplicate bug, exactly the class of bug prior batches found "
    "elsewhere). Ordinary capitalized-sentence-opener words that happen "
    "to precede a coincidental \"N to M\" (\"Expected 2 to 3 upper "
    "circuit\", \"Coming 15 to 30 Days view\" -- both from Equity99's "
    "text, see MOMENTUM_DENY in signals.py) are excluded by a small deny "
    "set, added and verified against this channel's own full history plus "
    "every other 'cash'-style channel.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch6 "
    "· see git log for commit sha"
)

BHARATH_MARKET_RESEARCH = (
    "Bharath's Market Research / SEBI Registered (channel 6) -- a "
    "high-volume options-tips broker channel (Bharath Billa): real "
    "intraday NIFTY/BANKNIFTY/SENSEX and stock option orders, running "
    "recap reposts of the SAME leg through the day, plus heavy "
    "subscription-discount promo spam.\n\n"
    "DOMINANT SHAPE: \"<ROOT> <STRIKE>CE/PE [Sep/June/... Series]\\n\\n"
    "Buy Range - <hi>/<lo>\\n\\nSL <price>\" (\"SOLARINDS 22500CE Sep "
    "Series\\n\\nBuy Range - 660/650\\n\\nSL 550\"). Was previously 76% "
    "entry=NULL (313 of 410 rows) -- RE_OPT's existing dash-range fallback "
    "only recognizes a \"-\"-separated pair immediately (within 20 chars) "
    "after the strike; this channel's own range separator is \"/\" and "
    "arrives after a \"Sep Series\"/\"JUNE SERIES\" annotation, up to 21 "
    "characters away. New RE_OPT_BUY_RANGE (60-char window, style-gated "
    "to 'options', set here) fills it; SL/TARGETS were ALREADY read "
    "generically by the existing message-level RE_SUPPORT/RE_TARGET "
    "fallback (\"SL <price>\"/\"Stoploss - <price>\"/\"TARGETS - "
    "<price>\") -- no new code needed there. Now 488 trades, entry=NULL "
    "down to ~290 (the remainder is either a message with genuinely no "
    "price stated at all -- \"PAYTM 1180CE looking good\\n\\nSL 34\" -- or "
    "a multi-leg end-of-day digest naming several legs' RESULTS with no "
    "per-leg entry, see TRAPS #2).\n\n"
    "TRAPS FOUND THE HARD WAY:\n"
    "1. This channel reposts the SAME option leg's running result later "
    "the same day with no \"Buy Range\" restated (\"INDUSTOWER 380CE SEP "
    "Series\\n11.2 to 13.5+\\nTarget 1 Done & Dusted\"). Once the entry "
    "message's real price is captured, this recap's own entry stays None "
    "-- and since (channel, trade, entry) differ (11.2 vs None), it used "
    "to mint a SECOND, blank-valued phantom Trade row for the same leg. "
    "Fixed channel-agnostically (see next section): a bare \"<price> to "
    "<price>\" restatement right after an option strike with NO SL "
    "anywhere else in the message is now dropped entirely rather than "
    "emitted with a blank entry.\n"
    "2. Multi-leg end-of-day digests (\"Trades given in PREMIUM group "
    "Yesterday!!\\n\\nSENSEX 78200CE - 150 to 200+...\\nPAYTM 1180CE - 39 "
    "to 44+...\\nSENSEX 78300CE - SL hit 30pts...\") still leave several "
    "legs at entry=NULL: the whole-message \"has SL anywhere\" heuristic "
    "in trap #1 is message-global, and one leg in the SAME digest stating "
    "\"SL hit\" makes every OTHER leg's genuinely-recap-only mention look "
    "like it might have its own SL, so none of them get dropped. Left "
    "unparsed rather than risk a wrong per-leg SL attribution -- would "
    "need per-leg-local context extraction to fix properly, out of scope "
    "for a targeted regex fix.\n\n"
    "CHANNEL-AGNOSTIC BUG FIXED WHILE WORKING THIS CHANNEL: see signals.py "
    "top-level notes -- the recap-with-no-SL skip in the RE_OPT loop is "
    "unconditional (not style-gated), verified via full-corpus check that "
    "\"no premium marker + a bare N-to-M recap right after the strike + no "
    "SL anywhere in the message\" is 619/620 real, SL-bearing FIRST-time "
    "entries for Stock Thunder (channel 51, kept) vs 51/52 genuine "
    "same-day recaps for this channel (correctly dropped).\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch6 "
    "· see git log for commit sha"
)

MARKET_MASTER_HUB = (
    "MARKET MASTER HUB (channel 19) -- a mixed cash/options tips "
    "channel: \"BUY #<SYM> AT <price>\\n\\nSL: <price>\\n\\nTARGETS: "
    "<p1>, <p2>, <p3>\" cash calls, and \"BUY #<SYM> <strike> CE "
    "<DD>-<MON>-<YYYY> AT <price>\" option calls with an explicit expiry "
    "date. 166 pre-existing trades, but riddled with two bugs (see "
    "CHANNEL-AGNOSTIC FIX below) that collapsed hundreds of different "
    "option legs onto a shared, wrong constant entry price -- fixed, now "
    "110 trades, all correctly priced.\n\n"
    "CHANNEL-AGNOSTIC BUG FIXED WHILE WORKING THIS CHANNEL:\n"
    "1. \"BUY #JIOFIN 270 CE 24-SEP-2026 AT 5.7\" -- RE_OPT's own optional "
    "trailing-NUM premium capture was reading the expiry date's DAY "
    "number (\"24\") as if it were the premium, discarding the real "
    "\"AT 5.7\" a few words later. Every option leg in this channel with "
    "an explicit \"DD-MON-YYYY\" expiry got entry stamped to a nonsense "
    "constant (24, 8, 28, ...) shared across dozens of UNRELATED "
    "symbols/strikes regardless of its own real stated price. Fixed in "
    "the RE_OPT loop: when the captured premium is immediately followed "
    "by \"-MON-YYYY\", it's discarded and replaced by the real price from "
    "the trailing \"AT <price>\" instead. Verified empirically unique to "
    "this channel across the full 82-channel corpus (420 occurrences, "
    "channel 19 only).\n"
    "2. \"MENON PISTON CMP 74 ... TGT 94-108-135 ... INVALID BELOW 65 WITH "
    "ON CLOSING BASED\" -- the word \"INVALID\" (this channel's own "
    "setup-invalidation sign-off, \"the call becomes invalid below X\") "
    "was read by the shared RE_CASH fallback as a second, phantom ticker "
    "(\"INVALID BELOW 65\"). Added \"INVALID\" to the shared STOP_WORDS "
    "deny list (common English word, never a real ticker).\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch6 "
    "· see git log for commit sha"
)

STOCK_MARKET_SCHOOL = (
    "STOCK MARKET SCHOOL - BANKNIFTY OPTIONS NIFTY OPTIONS STOCK "
    "(channel 81) -- an intraday SENSEX/NIFTY options + XAUUSD (gold) "
    "forex scalping channel, heavy on repeated running-LTP reposts of the "
    "SAME open call through the day.\n\n"
    "DOMINANT OPTIONS SHAPE: \"Buy Sensex 10 Sep 74700 CE\\nOnly In Range "
    "@ 180 - 200 Target 225 240 280 310 350 & Above\" -- the index name, "
    "then a title-cased \"<DAY> <MON>\" expiry (no year), then the strike. "
    "RE_OPT's own root-matcher structurally can't bridge \"Sensex \" "
    "(letters, space) into the day-number that follows -- this channel "
    "was at 7 of 1530 tracked messages before this pass. New "
    "RE_SMS_OPT_DATE/RE_SMS_RANGE_ENTRY + a new step 'options'-gated "
    "block in parse_message (set here), scoped to the small enumerated "
    "SENSEX/NIFTY/BANKNIFTY/FINNIFTY root set (not a bare `[A-Z]+`) so "
    "the case-insensitive month/CE-PE matching this needs can't also "
    "swallow an unrelated capitalized-word-plus-date sentence elsewhere. "
    "Requiring the \"Range @\" entry-trigger phrase is what keeps this "
    "channel-agnostic-safe AND avoids phantom duplicates: the channel's "
    "own repeated intraday reposts of the same leg (\"Dipped @ 180 se "
    "273\", \"Breakdown@ 4325 To 4308\") never restate \"Range\", so they "
    "correctly produce no signal instead of a second blank-valued Trade "
    "row. Verified empirically against the full 82-channel corpus: of "
    "931 corpus-wide matches for the date-option header shape, only this "
    "channel's own messages ever pair it with the word \"Range\". Now 161 "
    "trades, 0 blank entries.\n\n"
    "FOREX: \"Buy XAUUSD @4348-4345\\n\\nTarget - 4353 4357 4365\\n\\nStop "
    "Loss - Vip\" already parses correctly via the existing generic "
    "RE_VERB_FIRST + RE_RANGE dash-fallback with no new code -- "
    "\"Stop Loss - Vip\" (a non-numeric \"ask admin\" placeholder) "
    "correctly leaves stop_loss blank rather than fabricating a number, "
    "per the project's honesty convention. A second forex shape (\"If "
    "XAUUSD Falls & Sustain Below 4325 Sell for\") does NOT parse -- the "
    "shared RE_CASH's lazy word-bridge can't cross the \"&\" in \"Falls & "
    "Sustain\"; left unparsed rather than loosen a channel-agnostic "
    "regex for one channel's phrasing.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch6 "
    "· see git log for commit sha"
)

KUTTRAPALI26 = (
    "@kuttrapali26 (channel 77) -- a real market-commentary channel "
    "(FII/DII flow data, macro/geopolitical outlook, philosophy-of-"
    "trading posts), NOT a personal contact despite the @-handle-style "
    "name (already confirmed by a prior batch). No entry/target/SL trade "
    "calls anywhere in the 1524-message tracked history -- purely "
    "commentary and index-level/macro narration. All 3 pre-existing "
    "trades were phantoms: \"FII\"/\"DII\" from flow-data numbers "
    "(\"FII – Sold 5100Cr...\"), \"TATA\" from an unrelated \"TATA POWER "
    "ABOVE 300... Study & Continue holding... Not a buy/Sell "
    "recommendation... for the educational purpose\" long-term-portfolio "
    "post explicitly disclaimed as non-actionable. Classified "
    "style='promo'.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch6 "
    "· see git log for commit sha"
)

TRADING_MARVEL = (
    "The Trading Marvel (channel 62) -- a social-media-cross-posting "
    "channel (X/Instagram/Facebook links), long-term \"Time-2/3 year\" "
    "portfolio-building picks, and occasional genuine short/medium-term "
    "stock calls scattered among heavy promotional noise. Real shapes "
    "vary a lot (\"SBC EXPORTS\\nCMP-27.70\\nSL-22\", \"Rathi steel& "
    "power cmp 30 sl 26 tgt 40,60\", \"Electrosteel castings\\nCmp-83>Tgt-"
    "110/170/330>Sl-54\") -- no single dominant template worth a "
    "dedicated regex given how thin the actual signal density is (moved "
    "the channel from style='auto' to 'mixed' to activate this file's "
    "EXISTING shared 'mixed'-gated shapes -- e.g. Darshan's bare \"<name> "
    "from N to M\" recap and the symline-support shape -- rather than "
    "add channel-specific code; 1 -> 12 trades with just the style "
    "change plus the two STOP_WORDS fixes below).\n\n"
    "TRAPS FOUND THE HARD WAY: switching to 'mixed' style surfaced two "
    "phantom trades from this channel's own conversational prose matching "
    "Darshan's shared \"<words> from N to M\" recap shape (_darshan_recap_"
    "signal) as if the sentence's first word(s) were a ticker: \"If it "
    "rises from 200 to 300 then 20/30 points normal correction\" -> "
    "phantom \"IF IT RISES\", \"What you say now\\n1677 to 1877\" -> "
    "phantom \"WHAT YOU SAY NOW\", and (a different shape, "
    "RE_STOCKGAINERS_RECAP) \"Fired\\n700 to 960\" -> phantom \"FIRED\". "
    "Added \"IF\" to the shared STOP_WORDS set (used by "
    "_darshan_recap_signal's own symbol check) and \"WHAT\"/\"FIRED\" to "
    "STOCKGAINERS_DENY -- all three are common English words, never real "
    "tickers, verified against the full corpus before adding.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch6 "
    "· see git log for commit sha"
)

POWER_OF_STOCKS = (
    "Power Of Stocks (channel 33) -- a YouTube-live-session/educational "
    "channel with an 8-year tracked history (2018-2026): vague technical-"
    "analysis commentary (\"Trading in a small range, breaking of either "
    "side can big move happen\"), constant broker-referral-link promo "
    "spam (Zerodha/Upstox/Fyers/AliceBlue), and livestream announcements. "
    "Sampled the SL/target-bearing subset of messages specifically (35 of "
    "1389 tracked messages) -- every one is free-flowing prose describing "
    "a hypothetical setup rather than a stated actionable entry (\"34400 "
    "pe looks good if it break 42 again then can take a buy trade with "
    "strict sl of 25\", \"1 min chart of 37300ce... sl max 20 rs target "
    "min 1:2\") -- no clean, low-false-positive-risk shape to extract. "
    "0 pre-existing trades (correctly). Classified style='promo'.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch6 "
    "· see git log for commit sha"
)


def set_styles(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    updates = {
        11: ('cash', EQUITY99),
        22: ('cash', MOMENTUM_TRADES),
        6: ('options', BHARATH_MARKET_RESEARCH),
        19: ('options', MARKET_MASTER_HUB),
        81: ('options', STOCK_MARKET_SCHOOL),
        77: ('promo', KUTTRAPALI26),
        62: ('mixed', TRADING_MARVEL),
        33: ('promo', POWER_OF_STOCKS),
    }
    for channel_id, (style, notes) in updates.items():
        Channel.objects.filter(id=channel_id).update(style=style, style_notes=notes)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('traderacker', '0021_batch5_style_notes'),
    ]

    operations = [
        migrations.RunPython(set_styles, noop),
    ]
