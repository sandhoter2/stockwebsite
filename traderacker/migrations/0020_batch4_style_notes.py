# Sets Channel.style / style_notes for the 8 channels covered by the
# "batch4" full-history specialist pass (docs/AGENT_HANDOFF.md pattern):
# Stockizen Research, Finance With Sunil, Richie by Chase Alpha, Systematix
# Group Official, SUPER TRADER LAKSHYA, Stock Burner, Platinum Research,
# 20PAISA..COM. Data-only migration — safely no-ops if a channel doesn't
# exist yet (fresh/test DB), and is idempotent (re-running it just
# overwrites with the same values).
from django.db import migrations

FINANCE_WITH_SUNIL = (
    "Finance With Sunil — a structured broker-template option-tip channel "
    "(\"Stock Name- #SYM / Strike- <month> <strike> CE|PE <entry> / Lot "
    "Size- / SL- / Target-\") plus a \"Prime Members\" option-leg recap "
    "variant and occasional all-caps hashtag restatements.\n\n"
    "DOMINANT SHAPES:\n"
    "1. The structured \"Strike-\" option-order template — new "
    "_finsunil_signal, entry/SL/target read directly from their labelled "
    "fields.\n"
    "2. The \"Prime Members\" option-leg recap shape — new "
    "RE_FINSUNIL_OPT_RECAP.\n\n"
    "TRAPS: deliberately does NOT parse the \"Stock Name- #SYM\\n#SYM N To "
    "M ... Target Done\" restatement shape — it always restates an option "
    "leg already opened by an earlier Strike- message, and parsing it "
    "would mint phantom duplicate bare-symbol cash trades under the "
    "display-name hashtag instead of the real option leg. style set to "
    "'options' (not 'cash') specifically to avoid colliding with Short To "
    "Mid Term/Swing Trader Vishal's cash-gated RE_STMT_RECAP/"
    "RE_VISHAL_BOUGHT on this channel's own all-caps hashtag recaps.\n\n"
    "CHANNEL-AGNOSTIC FIX LANDED WHILE WORKING THIS CHANNEL: RE_CRYPTO's "
    "\"<SYM> LONG/SHORT\" match had no restriction to real crypto/"
    "leveraged tickers, so ordinary prose like \"WE WERE SHORT FROM "
    "MORNING!!\" matched with sym=\"WERE\" and produced a permanent "
    "blank-entry phantom trade everywhere in the 82-channel corpus (196 "
    "matches, 38 distinct non-ticker \"symbols\", all ordinary English "
    "words/macro nouns used as verbs/adjectives). Fixed by dropping any "
    "entry-less RE_CRYPTO match regardless of asset_class (previously "
    "only checked asset_class == 'crypto', which this false match never "
    "gets) — the two real crypto matches with a stated entry (Serezha "
    "Calls' CYBER/AEVO legs) are unaffected.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch4 "
    "(channel/batch4) · batch4 specialist pass"
)

STOCKIZEN_RESEARCH = (
    "Stockizen Research (SEBI Registered) — cash-equity/index swing and "
    "intraday calls, mostly a structured \"<NAME> (NSE: <TICK>) - "
    "POSITIONAL SWING TRADE / ENTRY ZONE: X - Y / SL: Z / TARGET 1: A\" "
    "block, plus occasional \"INTRADAY\\n\\nNIFTY SEP FUT SHORT\\n\\n<N> "
    "TO <M>\" futures calls picked up by the shared RE_STOCKGAINERS_RECAP "
    "shape.\n\n"
    "DOMINANT SHAPE: the structured swing-trade block — new "
    "_stockizen_swing_signal, entry=first number of ENTRY ZONE, "
    "target=TARGET 1, stop_loss=SL. style set to 'mixed'.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch4 "
    "(channel/batch4) · batch4 specialist pass"
)

RICHIE_CHASE_ALPHA = (
    "Richie by Chase Alpha — index/stock option-order calls, dominant "
    "shape \"NIFTY 19500 CE CMP 215 add till 210 SL 170 Target "
    "260-280-300\", \"BANKNIFTY 47600 PE CMP 40 Hero Zero\" — a bare "
    "\"CE|PE CMP <price>\" inline entry-price fallback right after the "
    "strike, with no parenthetical expiry between them (unlike Ashika "
    "Calls' shape).\n\n"
    "FIX: added the CMP-inline entry fallback to the shared option-leg "
    "loop, style-gated to 'options' (this channel's own style) — verified "
    "empirically the \"(CE|PE) CMP <price>\" adjacency is 0 occurrences "
    "across every other 'options'-style channel's history.\n\n"
    "TRAPS: 'mixed' style was considered and REJECTED for this channel "
    "(would have picked up the CMP fallback \"for free\" via existing "
    "infrastructure) after finding it collides with two other mixed-style "
    "channels' shared patterns on this channel's own text — Trading Ideas "
    "By Darshan's RE_DARSHAN_RECAP (a ticker-unrestricted \"<free text> "
    "from N to M\" shape) turns \"BANK NIFTY 59000 CE on App from 18 to "
    "150\" into a phantom \"BANK NIFTY 59000 CE ON APP\" trade, and "
    "\"Todays 2nd pick Granules from 482 to 494\" into a phantom \"TODAYS "
    "2ND PICK GRANULES\" trade — neither a real signal. 'options' style "
    "avoids both collisions, which is why it was kept.\n\n"
    "CHANNEL-AGNOSTIC INTERACTION BUG FOUND AND FIXED: the new CMP "
    "fallback would otherwise have broken 𝐅𝐈𝐍𝐀𝐍𝐂𝐈𝐀𝐋 𝐒𝐀𝐑𝐓𝐇𝐈𝐒's existing "
    "RE_FINSARTHI_OPT dedup (only relevant to 'mixed'-style channels, not "
    "Richie's own 'options' style, but the dedup's own assumption broke): "
    "it only removed a truncated-root option placeholder (\"NIFTY 45500 "
    "CE\" when the real text was \"BANK NIFTY 45500 CE\") when that "
    "placeholder's entry was still None. Once a CMP-inline fallback can "
    "fill that placeholder's entry before Finsarthi's own step runs, the "
    "removal condition silently stopped firing and both a correct and a "
    "wrong/truncated row survived side by side. Fixed to always remove "
    "the matching-suffix placeholder regardless of its entry, and carry "
    "that entry forward onto the correct row if Finsarthi's own capture "
    "didn't find one.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch4 "
    "(channel/batch4) · batch4 specialist pass"
)

SYSTEMATIX_GROUP = (
    "Systematix Group Official — broker-style cash/futures calls, "
    "dominant shape \"Buy <SYM|Company Name...> in cash @ <entry>"
    "[-<entry2>] SL <sl> TGT <t1>[)... N)...]\" plus \"Fut\"/bare \"in "
    "<price>\"/\"in at <price>\" variants, and a separate weekly \"Stock "
    "Picks of the week : Buy - <NAME> / Buy Range : Rs. X - Rs. Y / Stop "
    "Loss: Rs. Z / Target 1: Rs. A\" block. Tickers are almost always "
    "multi-word company names (often \"... Ltd\"), invisible to the "
    "shared single-word RE_VERB_FIRST/RE_BUYSELL, whose grammar also has "
    "no room for this channel's universal \"in cash\"/\"in at\" filler "
    "between the symbol and the price.\n\n"
    "DOMINANT SHAPES: new _systematix_cash_signal/_systematix_weekly_"
    "signal, style-gated to 'cash'; verified 0 false positives against "
    "every other 'cash'-style channel's full history. 83 -> 801 trades.\n\n"
    "TRAPS: a single-word root (\"PIIND\", \"AUBANK\", \"CUMMINSIND\", "
    "...) is ALSO matched by the generic fallback that runs earlier in "
    "parse_message(); rather than skip when that placeholder already "
    "exists (as every other per-channel shape does), this step corrects "
    "its entry/target/stop_loss from the more careful parse when the "
    "generic one is missing data on the same leg (confirmed by matching "
    "entry price).\n\n"
    "CHANNEL-AGNOSTIC FIX LANDED WHILE WORKING THIS CHANNEL: RE_TARGET/"
    "RE_TARGET_MIXED's number match had no way to skip a ranked \"<n>)\" "
    "prefix before a multi-target list's real price, so \"TGT 1)3575 "
    "2)3470\" was read as target=1 for EVERY channel using this ranked-"
    "list phrasing (270 occurrences in this channel's own history, the "
    "dominant reason 11 of its 801 new trades initially came out with a "
    "garbage target=1). Fixed with an optional \"<rank>)\" skip. A "
    "full-corpus check found only one other occurrence of this adjacency "
    "(Trading Ideas By Darshan's astrology \"Pro Astro View :\\n1) 26 "
    "Feb : Mercury Turns Retrograde...\" — a numbered list, not a trade "
    "target, and that message has no trade signal for the fix to affect "
    "either way).\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch4 "
    "(channel/batch4) · batch4 specialist pass"
)

SUPER_TRADER_LAKSHYA = (
    "SUPER TRADER LAKSHYA (#STL) — pure macro/YouTube-live commentary "
    "channel (market outlook talk, live-stream announcements, YouTube "
    "links). Sampled the FULL date range: zero entry/SL/target price "
    "levels anywhere in the tracked history — real trades, if any, are "
    "only shared in a paid VIP group not present in this corpus.\n\n"
    "style set to 'promo' (skip). Not a coverage miss — a genuine absence "
    "of parseable signal content.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch4 "
    "(channel/batch4) · batch4 specialist pass"
)

STOCK_BURNER = (
    "Stock Burner — support/resistance market commentary and YouTube vlog "
    "promos, same pattern as SUPER TRADER LAKSHYA. No real entry/SL/"
    "target signals anywhere in the tracked history. The one pre-existing "
    "trade (\"RELIANCE\" @ 2636) was itself a false positive from market "
    "commentary (\"IF RELIANCE TODAY SUSTAIN ABOVE 2636 WE WILL SEE SOME "
    "RECOVERY ON NIFTY\" — a Nifty-direction remark, not a Reliance "
    "call), confirming 'promo' is the right classification, not a "
    "coverage miss.\n\n"
    "style set to 'promo' (skip).\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch4 "
    "(channel/batch4) · batch4 specialist pass"
)

PLATINUM_RESEARCH = (
    "Platinum Research — dense, ALL-CAPS-heavy technical-analysis prose "
    "(\"...bullish RSI\\n1360 CE keeping in watchlist\", \"CMP - 33\", "
    "\"BREAKOUT HERE\") mixed with genuine cash/option calls. style set "
    "to 'mixed'.\n\n"
    "TRAPS: this channel's dense jargon was feeding common TA vocabulary "
    "into the shared option/cash regexes as phantom tickers — 23 of the "
    "channel's pre-fix 44 trades were bogus rows literally named CMP/"
    "HIGH/CLOSING/BREAKOUT/POINTS/WATCH/WATCHLIST/ROCKET/READY/TIMEFRAME/"
    "TF/RSI/SUSTAIN/LIST/NUMBERS/STRANGLE/EMA/SAY instead of a real "
    "symbol. Fixed by adding all of these to the GLOBAL STOP_WORDS set "
    "(channel-agnostic — checked against every channel's already-parsed "
    "Trade rows first: none is a real ticker's full name anywhere in the "
    "82-channel history; a ticker that merely STARTS with one of these as "
    "a substring, e.g. EMAMILTD/CMPDI, is a different exact token and "
    "unaffected). Also found the same \"wrong line's phrase mistaken for "
    "the symbol\" trap for Trading Ideas By Darshan's RE_DARSHAN_RECAP on "
    "this channel's \"NESTLE BREAKOUT - Decent numbers !!\\nProper 2X "
    "trade from 27 to 54+\" and extended DARSHAN_VERB_DENY with TRADE/"
    "PROPER/2X. 44 mostly-noise trades -> 34 substantially cleaner ones "
    "(a real symbol backs every remaining row's option/cash leg).\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch4 "
    "(channel/batch4) · batch4 specialist pass"
)

PAISA_20 = (
    "20PAISA..COM ( Nifty & BankNifty Option ) — a pure Nifty/BankNifty/"
    "Sensex index-option tip channel, heavy emoji use (💙✅🔥🌪), zero cash-"
    "equity calls. 1783 tracked messages, full date range 2026-03-30 to "
    "2026-09-11.\n\n"
    "DOMINANT SHAPES (0 trades existed before this pass — the channel's "
    "mixed-case \"Nifty\"/\"Sensex\" root was invisible to the all-caps-"
    "only RE_OPT):\n"
    "1. \"PREMIUM ✅✅\\n\\n\\n\\n\\nNifty 22500CE\\n\\n\\n\\n\\n175 To "
    "260++💙💙✅✅\" — an already-mixed-case index-option tip that states "
    "BOTH the entry premium and the level it already ran to on the very "
    "next non-blank line, joined by \"To\". New RE_OPT_ENTRY_TO_TARGET, "
    "consumed inside the existing (Ashika Calls-authored) RE_OPT_INDEX_CI "
    "mixed-case-root loop right after the CMP-in-parens fallback — "
    "anchored immediately after the CE/PE match so it only ever reads "
    "the number pair belonging to THAT leg.\n"
    "2. \"Nifty 22400PE Good Above @ 172\\n\\n\\nSl : 152\" — a forward "
    "trigger call with entry+SL, no target. Already handled by the "
    "existing shared message-level RE_PREMIUM/RE_SUPPORT_MIXED fallback "
    "once the option root/strike is captured by RE_OPT_INDEX_CI; no new "
    "regex needed.\n"
    "3. \"✍ Done Of The Day ✍\\n\\n\\n✅Nifty 22500CE @ 175 To 260+\\n\\n"
    "\\n✅Nifty 22600CE @ 177 To 193\\n...\" — an end-of-day recap "
    "restating 3-8 legs in ONE message, same \"<entry> To <exit>\" shape "
    "as #1 but with a leading \"@\". Same RE_OPT_ENTRY_TO_TARGET handles "
    "it per-leg (it tolerates an optional leading \"@\").\n\n"
    "CHANNEL-AGNOSTIC BUG FOUND AND FIXED while adding shape #3's "
    "multi-leg recap support: the shared message-level "
    "\"sig['entry'] is None -> fill from RE_PREMIUM.search(text)\" "
    "fallback near the end of parse_message() does a single text-wide "
    "search, not one per leg — so a recap leg with NO stated price at "
    "all (\"✅BNF 55900CE @ SL Taken\", \"✅Nifty 24000CE @ 20 Point SL\") "
    "was getting silently stamped with the FIRST \"@ <price>\" found "
    "anywhere else in the same multi-leg message (an unrelated leg's "
    "entry). New RE_OPT_NO_PRICE_CLOSE recognizes this channel's specific "
    "\"@ SL Taken\"/\"@ SL Hit(t)\"/\"@ <N> Point SL\" no-price closure "
    "phrasing and drops that leg entirely instead (checked channel-"
    "agnostic-safe: 54 occurrences, all channel 1, 0 elsewhere in the "
    "82-channel corpus — so left unconditional/ungated, applied in both "
    "the primary uppercase RE_OPT loop and the mixed-case RE_OPT_INDEX_CI "
    "loop, since this channel's roots appear in both cases).\n\n"
    "SECOND CHANNEL-AGNOSTIC BUG FOUND AND FIXED: plain index-level "
    "commentary with no trade content at all (\"Nifty Strong Support\\n"
    "\\n\\n\\n24000 To 24050\", a support-ZONE note) matched Stock "
    "Gainers'/Ritvi Taneja's shared RE_STOCKGAINERS_RECAP loose "
    "\"<up-to-4-word line>\\n<N to M>\" shape, since its first word "
    "(\"NIFTY\") is a real index root and passes the existing first-word-"
    "only STOCKGAINERS_DENY check — producing a phantom \"NIFTY STRONG "
    "SUPPORT\" trade. New STOCKGAINERS_TRAILING_DENY checks the "
    "candidate's trailing TWO words specifically (kept separate from "
    "STOCKGAINERS_DENY's first-word-only set, rather than adding STRONG/"
    "SUPPORT to it, because Stockizen Research's genuine \"NIFTY SEP FUT "
    "SHORT\" futures call also ends in a lone STOCKGAINERS_DENY word "
    "(\"SHORT\") and must keep matching — verified this doesn't drop "
    "that trade).\n\n"
    "TRAPS: a leg restated TWICE in the same message under the identical "
    "(root, strike, right) key (e.g. \"Nifty 24300PE Good Above @ 180\" "
    "immediately followed by \"Nifty 24300PE\\n\\n\\n180 To 205++\" in "
    "the same message) collapses onto whichever occurrence's RE_OPT_"
    "INDEX_CI match comes first (the existing trade-string dedup, shared "
    "with every other per-channel shape in this file) — the SECOND "
    "occurrence's \"180 To 205\" target is deliberately lost rather than "
    "overwriting the first row, same \"first occurrence wins\" convention "
    "used throughout this file.\n\n"
    "DELIBERATELY UNPARSED: \"✅ Good Morning Traders ✅\" / open-range-"
    "resistance-support market-outlook posts with no option strike at "
    "all; \"🏆 JOIN PREMIUM 🏆\" subscription-pitch posts; a recap leg "
    "whose only annotation is non-numeric (\"@ CTC Near Exit.\") stays "
    "entry=None rather than guessing — correctly conservative, verified "
    "no shared fallback fills it either. style set to 'mixed' (needed "
    "for the pre-existing RE_OPT_INDEX_CI mixed-case-root machinery this "
    "channel relies on). 371 trades from 0 before this pass.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch4 "
    "(channel/batch4) · batch4 specialist pass"
)


def set_styles(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    updates = [
        ('Stockizen Research - SEBI Registered', 'mixed', STOCKIZEN_RESEARCH),
        ('Finance With Sunil', 'options', FINANCE_WITH_SUNIL),
        ('Richie by Chase Alpha', 'options', RICHIE_CHASE_ALPHA),
        ('Systematix Group Official', 'cash', SYSTEMATIX_GROUP),
        ('SUPER TRADER LAKSHYA (#STL)', 'promo', SUPER_TRADER_LAKSHYA),
        ('Stock Burner', 'promo', STOCK_BURNER),
        ('Platinum Research', 'mixed', PLATINUM_RESEARCH),
        ('20PAISA..COM ( Nifty & BankNifty Option )', 'mixed', PAISA_20),
    ]
    for name, style, notes in updates:
        Channel.objects.filter(name=name).update(style=style, style_notes=notes)


def unset_styles(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    names = [
        'Stockizen Research - SEBI Registered',
        'Finance With Sunil',
        'Richie by Chase Alpha',
        'Systematix Group Official',
        'SUPER TRADER LAKSHYA (#STL)',
        'Stock Burner',
        'Platinum Research',
        '20PAISA..COM ( Nifty & BankNifty Option )',
    ]
    Channel.objects.filter(name__in=names).update(style='auto', style_notes='')


class Migration(migrations.Migration):

    dependencies = [
        ('traderacker', '0019_batch3_style_notes'),
    ]

    operations = [
        migrations.RunPython(set_styles, unset_styles),
    ]
