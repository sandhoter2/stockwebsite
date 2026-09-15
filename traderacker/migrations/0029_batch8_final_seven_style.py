# Batch8 (final batch): style / style_notes for the last 7 channels with
# meaningful message volume -- docs/AGENT_HANDOFF.md pattern. One combined
# migration for all 7, per the batch instructions. Data-only, safely no-ops
# on a fresh/test DB (filter().update() on missing ids is a no-op), and
# idempotent (re-running just overwrites with the same values).
from django.db import migrations

WORKTREE = "/Users/mamathap/Downloads/worktrees/batch8"
LAST_AGENT = f"2026-09-15 · {WORKTREE} · see git log for commit sha"

TSP_FINANCE = (
    "TSP Finance (channel 67, 723 msgs) -- a general markets/news feed: "
    "corporate-action bulletins (\"AFFLE: CO APPROVE STOCK SPLIT IN RATIO "
    "1:5\"), macro/GDP data, IPO listing notes, long-form broker-report "
    "excerpts (\"CGS-CIMB: Bajaj Finance Ltd | From conventional lending to "
    "a Fintech way\"), daily index/forex/commodity snapshots (\"TSP Finance "
    "Update - 30/01/26\\nSensex:82269.78(-296.59)...\"), and personal "
    "commentary threads (\"Car trade tech: Personal investment update\"). It "
    "is NOT a signals channel: sampled the full corpus (every ~15th message "
    "plus keyword-filtered search on SL/TGT/entry/target/CE/PE) and found "
    "zero entry+stop-loss+target calls anywhere in the history.\n\n"
    "Before this pass the generic parser had already minted 2 phantom "
    "Trade rows purely from stray text matching option/cash regexes: "
    "'FY23 PE' (from ordinary fiscal-year prose, not an option) and "
    "'STEEL' @12.0 (a stray number in commentary, not a call). Both "
    "disappear once style='promo' short-circuits parse_message "
    "(signals.py:~1876, the existing opt-out) for this channel.\n\n"
    "style='promo'. No regex changes; no test added (no genuine bug in "
    "shared code, purely a channel-classification fix).\n\n"
    f"last agent: {LAST_AGENT}"
)

CHART_WALLAH = (
    "Chart Wallah (channel 78, 713 msgs) -- an equity-research/commentary "
    "channel: broker target-price call-outs (\"Motilal Oswal on JSW Infra "
    "\\nTP : 360 (+40%)\"), business-update threads, sector deep-dives, "
    "\"Top N Turnaround/Breakout Stocks\" idea lists with vague percentage "
    "upside ranges (\"20% - 30% Upside targets\"), and outright group-promo "
    "spam (\"JOIN GrowX OFFICIAL GROUP\"). Sampled the full corpus "
    "(spread sample + SL/TGT/entry/CE/PE keyword search, 100 hits, all "
    "either broker TP call-outs or unrelated prose using the word "
    "'target'/'entry' non-numerically). No message ever states an entry "
    "price with a stop-loss/target pair in a trackable-trade shape -- these "
    "are research opinions and price-target notes, not signals with an "
    "entry the reader is meant to act on at a specific level. 0 trades "
    "before and after this pass, which is the honest state.\n\n"
    "style='promo'. No regex changes; no test added.\n\n"
    f"last agent: {LAST_AGENT}"
)

MARKET_MAESTRO = (
    "Market Maestro (channel 18, 698 msgs) -- an index-options tipster, "
    "NIFTY/SENSEX CE/PE only. Dominant shape (already correctly parsed by "
    "the existing generic option path, no channel-specific regex needed): "
    "\"#NIFTY 24100 CE\\n\\nABOVE - 100\\n\\nTRG 110/120/130+\\n\\nSL VIP\" "
    "-- entry/target read fine; the literal string 'VIP' in the SL slot is "
    "deliberately left un-numeric (there is no SL price to extract, and "
    "none should be fabricated).\n\n"
    "TRAP verified NOT a false positive: this channel interleaves an "
    "\"account handling\" scam ad after most calls -- \"TODAY LIVE PROFIT "
    "\\u25b6\\ufe0f\\u25b6\\ufe0f\\n\\n\\n\\U0001f4a5\\U0001f4a5 1,52,250\\n\\n\\nIN "
    "ACCOUNT HANDLING WORK DONE BY OUR EXPERTS\". This is not a real "
    "profit-booking on a tracked leg (it is a fixed pitch for a managed-"
    "account product, with a large invented rupee figure). Confirmed by "
    "direct test that parse_message() already returns [] for it -- the "
    "emoji/newline clutter between 'PROFIT' and the number breaks both "
    "RE_PROFIT_PRE and RE_PROFIT_POST, so no fix was needed here, but this "
    "is recorded so a future agent doesn't 'fix' it into matching.\n\n"
    "Also present, deliberately left unparsed: \"<price>\\U0001f525\\U0001f525\\U0001f525\\U0001f525\" "
    "bare price-ticker reposts and \"2ND TARGET ARCHIVE\" recap lines with "
    "no symbol repeated -- there is no reliable way to attribute these to "
    "one specific open leg among several, so all 59 trades sit Open with no "
    "fabricated close. This mirrors the Ritvi Taneja precedent (§5 of the "
    "handoff): a close with no stated, attributable price/rupee figure "
    "stays Open rather than being guessed at.\n\n"
    "style left at 'auto' (already yields 59 correctly-shaped Open trades; "
    "no channel-specific regex block gated to another style applies to "
    "this header shape). No regex changes; no test added.\n\n"
    f"last agent: {LAST_AGENT}"
)

INDEX_TRADING_NITIN = (
    "Index trading with CA Nitin Murarka (SMC) (channel 15, 696 msgs) -- "
    "an index-options tipster, NIFTY/SENSEX/BANKNIFTY CE/PE. House style "
    "splits a call across two-plus separate messages sharing the same "
    "\"<INDEX> <DAY> <MON> <STRIKE> CE/PE\" header (e.g. \"NIFTY 11 Aug "
    "24550 CE\"): one message carries the entry (\"ONLY IN RANGE   \\U0001f449 "
    "115 - 118\"), a later one carries target/SL (\"TGT \\U0001f3af - 130, "
    "157\\nSL \\u26a1  -  Exit if 1-min candle body closes at 109\"). Also "
    "posts bare price-ticker reposts (\"189\\U0001f525\"), SL-trail updates "
    "(\"Sl update to 413\"), extra-leg adds (\"ADD SENSEX 76100 ce\"), and "
    "heavy \"Slot\"/\"Help and Money Booster Plan\" WhatsApp-referral promo "
    "spam interleaved throughout (correctly unparsed -- no prices in the "
    "shape the parser reads).\n\n"
    "BUG FOUND AND FIXED (channel-specific, style-gated): the "
    "\"<INDEX> <DAY> <MON> <STRIKE> CE/PE\" header already had a dedicated "
    "path -- RE_SMS_OPT_DATE + RE_SMS_RANGE_ENTRY, style-gated to "
    "style=='options' (signals.py ~1872-1904), built for STOCK MARKET "
    "SCHOOL's plain \"Range @ <price>\" entry trigger. This channel's own "
    "entry trigger is \"ONLY IN RANGE\" followed by an emoji arrow "
    "(\\U0001f449) before the number, and the old RE_SMS_RANGE_ENTRY "
    "(`\\bRange\\b\\s*@?\\s*NUM`) only tolerated whitespace or a literal '@' "
    "between the keyword and the number -- the emoji broke every match, so "
    "this channel's dominant entry shape produced 0 trades even though the "
    "header itself matched. Widened RE_SMS_RANGE_ENTRY to "
    "`\\bRange\\b[^\\d\\n]{0,15}NUM` (tolerates any short run of "
    "non-digit decoration -- emoji, dashes, colons -- between the keyword "
    "and the price). Verified channel-agnostic-safe: diffed old vs new "
    "regex on every RE_SMS_OPT_DATE match across the full 82-channel corpus "
    "-- all 45 behavior changes land exclusively on channel 15, zero effect "
    "on any other channel (including the other 11 style='options' "
    "channels, whose own 'Buy Range - x/y' shape is handled by a separate "
    "regex, RE_OPT_BUY_RANGE, not this one).\n\n"
    "style changed 'auto' -> 'options' (required to enable the "
    "RE_SMS_OPT_DATE/RE_SMS_RANGE_ENTRY path above).\n\n"
    "LEFT DELIBERATELY UNPARSED: SL-trail-only messages (\"Sl update to "
    "413\") and range-continuation adds (\"ADD SENSEX 76100 ce\") with no "
    "repeated header -- same non-attributable-recap reasoning as Market "
    "Maestro above. No rupee-figure profit statements were found anywhere "
    "in this channel's history, so realized stays blank throughout, "
    "consistent with the Ritvi Taneja honesty precedent.\n\n"
    "Test added: test_index_trading_nitin_range_arrow_entry (realistic-but-"
    "not-verbatim, covers the emoji-arrow entry shape).\n\n"
    f"last agent: {LAST_AGENT}"
)

STOCKEXPLODEROP = (
    "Stockexploderop (channel 53, 687 msgs) -- hype/chatter promoting a "
    "paid product called 'swingalgo' (a technical-indicator add-on), mixed "
    "with Hinglish market banter and stray stock-name mentions. Sampled the "
    "full corpus (spread sample + SL/TGT/entry/target/CE/PE keyword search, "
    "87 hits). Every hit is narrative prose, never a structured call: "
    "\"CONFIPET 5% SL HIT. Part n parcle of life' Taking loss is also an "
    "art\", \"0 stop loss 4 successful trades! When book words came true\", "
    "\"we are humans hamare stop loss bhi hit hote h!\" -- these reference "
    "stop-losses and targets in the abstract/retrospective, never as an "
    "actionable entry+level a reader could act on. No message anywhere "
    "states an entry price for a specific instrument. 0 trades before and "
    "after this pass, which is the honest state.\n\n"
    "style='promo'. No regex changes; no test added.\n\n"
    f"last agent: {LAST_AGENT}"
)

STOCK_MARKET_ADDA = (
    "STOCK MARKET ADDA ️ (channel 50, 399 msgs -- grew well past the "
    "16-26-msg 'near-blind' bucket the handoff doc's §2 snapshot recorded "
    "it in; re-triaged fresh here) -- a news/IPO-tracker feed: IPO listing-"
    "day updates (\"SHIPROCKET IPO LISTED AT ₹131.00 ... PEOPLE WHO GOT "
    "ALLOTMENT CAN EXIT OR HOLD WITH THE SL OF ₹122.00 FOR 5 YEARS\"), GMP/"
    "subscription tables, quarterly-results bulletins, block-deal reports, "
    "macro calendars, and generic financial-literacy listicles. Sampled the "
    "full corpus (spread sample + keyword search, 101 hits). The "
    "'SL OF ₹X' phrasing recurs often but is a passive long-term "
    "hold/exit suggestion for IPO allottees on a listing-day fait accompli "
    "(no distinct entry price separate from the already-known listing "
    "price, no target, not a call to open a new tracked position) -- "
    "structurally different from a trade signal, so it is correctly not "
    "read as one. 0 trades before and after this pass.\n\n"
    "style='promo'. No regex changes; no test added.\n\n"
    f"last agent: {LAST_AGENT}"
)

BEAT_THE_STREET = (
    "Beat The Street Equity Research Reports | Books (channel 5, 231 msgs "
    "-- the handoff doc's §2/bucket-D snapshot recorded only 2 messages; "
    "stale, re-triaged fresh here) -- a research-report distribution "
    "channel: PDF report drops (\"Mirae Asset Sharekhan Morning Tiger 10 "
    "Aug 2026.pdf\"), broker target-price call-outs (\"PL Capital sees 22% "
    "UPSIDE in HealthCare Global Enterprises\"), bulk/block-deal digests, "
    "IPO notes, and management-interview summaries. Sampled the full "
    "corpus (spread sample + keyword search, 48 hits). All are analyst "
    "opinions/target prices or informational digests -- never an entry "
    "price with a stop-loss the reader is meant to act on. 0 trades before "
    "and after this pass, which is the honest state.\n\n"
    "style='promo'. No regex changes; no test added.\n\n"
    f"last agent: {LAST_AGENT}"
)

STYLES = {
    67: ('promo', TSP_FINANCE),
    78: ('promo', CHART_WALLAH),
    18: ('auto', MARKET_MAESTRO),
    15: ('options', INDEX_TRADING_NITIN),
    53: ('promo', STOCKEXPLODEROP),
    50: ('promo', STOCK_MARKET_ADDA),
    5: ('promo', BEAT_THE_STREET),
}


def set_styles(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    for channel_id, (style, notes) in STYLES.items():
        Channel.objects.filter(id=channel_id).update(style=style, style_notes=notes)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('traderacker', '0028_batch7_vizu_style'),
    ]

    operations = [
        migrations.RunPython(set_styles, noop),
    ]
