# Sets Channel.style / style_notes for the 8 channels covered by the
# "batch5" full-history specialist pass (docs/AGENT_HANDOFF.md pattern):
# Usha's Analysis, TheDoji, Sairam Stocks, LIVELONG HARI, Stockbox Trading,
# Equiideas, Learning @ PlutusAdvisors, Theta Gainers. Data-only migration
# — safely no-ops if a channel doesn't exist yet (fresh/test DB), and is
# idempotent (re-running it just overwrites with the same values).
from django.db import migrations

USHA_ANALYSIS = (
    "Usha's Analysis (channel 68) — a paid-tip options/futures/equity "
    "broker channel: real intraday option/futures trade updates and "
    "recaps, short-term equity calls, plus heavy subscription-combo-pack "
    "promo spam.\n\n"
    "DOMINANT SHAPES:\n"
    "1. Option leg header with the expiry MONTH as its own word between "
    "the underlying and the strike -- \"BHARATFORG JUNE 1900 CE\\n\\n88 TO "
    "124\", \"ZENTEC JULY 2700 CE\". RE_OPT's root regex can't bridge "
    "\"BHARATFORG \" (letters-space-letters) to the strike, so it was "
    "matching starting at \"JUNE\" instead and silently dropping the real "
    "ticker -- new RE_TICKER_MONTH_OPT (a channel-agnostic-gated 'mixed' "
    "style step, see signals.py) recovers the real root; entry comes from "
    "the recap's \"<entry> TO <exit>\" first number, same convention as "
    "Options Train's own recap shape elsewhere in this file.\n"
    "2. Live cash-equity entry -- \"SHORT TERM EQUITY\\n\\nQUADFUTURE AT "
    "485\\n\\nTARGET 520,544+\\n\\nSTOP LOSS TO PREMIUM\" -- new "
    "_usha_at_entry_signal, deliberately case-SENSITIVE and TARGET-"
    "anchored so it can't fire on ordinary lower/mixed-case \"<word> at "
    "<price>\" prose elsewhere in the shared 'mixed'-style corpus.\n\n"
    "TRAPS: many messages are pure \"<price> TO <price>\" recaps with no "
    "restated ticker (\"ZENTEC\\n\\n1730 TO 1885\\n\\n155 POINTS IN A "
    "DAY\") -- these DO produce an Open trade via the existing generic "
    "RE_STOCKY_RECAP fallback (bare ticker + N to M within 60 chars, "
    "'mixed'-gated); left as-is, consistent with how every other "
    "channel's identical recap shape is already treated. \"STOP LOSS TO "
    "PREMIUM\" (i.e. no stop level stated) is deliberately left blank, "
    "never fabricated.\n\n"
    "CHANNEL-AGNOSTIC FIX LANDED WHILE WORKING THIS CHANNEL: the plain "
    "RE_OPT loop's existing 3-letter-month-abbreviation skip (\"APR\", "
    "\"JUL\", ...) was extended to also catch the FULL month word "
    "(\"JUNE\", \"JULY\", ...) as a bare root -- verified via full-corpus "
    "diff this alone also cleans up phantom \"APRIL 4300 CE\"/\"JULY 13000 "
    "CE\" rows in channel 79 (Eqwires), which has the same shape but no "
    "dedicated recovery step (still 'auto' style) -- no trade beats a "
    "wrong one there. The new RE_TICKER_MONTH_OPT recovery step itself "
    "(gated to 'mixed') also legitimately recovers real tickers in "
    "channels 3, 26, and 54 (all already 'mixed' from earlier batches, "
    "sharing this same house shape) -- confirmed each new row via its "
    "source message before accepting the diff.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch5 "
    "· see git log for commit sha"
)

THEDOJI = (
    "TheDoji (channel 63) -- an educational/investing-workshop channel: "
    "market commentary in ALL CAPS, webinar/workshop promos, and "
    "long-term position-BUILDING calls (\"STOCK 1 : DABUR, E1 WITH 30K\") "
    "that state a tranche number and capital amount but NEVER a rupee "
    "entry/SL/target price. Classified style='promo': every one of its 18 "
    "pre-existing trades was a phantom row created by RE_CASH's lazy "
    "word-bridge reading an ordinary ALL-CAPS English word right before "
    "\"ABOVE/BELOW <price>\" as if it were a ticker (\"DETAIL SUPPORT "
    "RESISTANCE I WILL SHARE... FOR NOW ALL GOOD ABOVE 23300\" -> phantom "
    "\"DETAIL\"; similarly \"IMMIDIATELY\", \"CLEAR\", \"HAVE\", "
    "\"BULLISH\", \"REVERSAL\", \"AGAIN\", \"F&O\", \"BEARISH\", "
    "\"EXCELLENT\", \"ANYTHING\", \"LONG\" -- none a real ticker). The "
    "channel never states an actionable price level for its actual "
    "investment calls (\"E1 WITH 30K\" = entry tranche 1 with Rs 30,000 "
    "capital, no price), so there is nothing for this parser's "
    "price-level model to track honestly -- promo is the correct, "
    "sufficient fix, not a per-word STOP_WORDS whack-a-mole (this "
    "channel's ALL-CAPS prose would keep minting new false positives from "
    "novel English words indefinitely).\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch5 "
    "· see git log for commit sha"
)

SAIRAM_STOCKS = (
    "Sairam Stocks (channel 41) -- a paid BANKNIFTY/NIFTY option-tip "
    "channel with heavy \"JOIN OUR PREMIUM GROUP\" spam, including a "
    "repeated countdown-hype pattern that reposts the SAME header with an "
    "incrementing exit level every few seconds (\"1090 ₹ to 1100 "
    "₹\", \"...1105₹\", \"...1110₹\", ...) -- these "
    "correctly produce no signal (no BUY/entry wording of their own).\n\n"
    "DOMINANT SHAPE: \"<INDEX> <STRIKE>  <CALL|PUT> <MONTH> <YEAR>\\n\\n"
    "\U0001F4CA BUY ABOVE : <price>\\n\\n\U0001F3AFTGT : "
    "<t1>-<t2>-<t3>+++\\n\\n☠️SL : AS PER CHART\" (150 tracked "
    "messages), plus a terser \"BUY ABOVE <price> LEVEL ONLY\" / \"BUY "
    "ABOVE ONLY <price> LEVEL\" variant. style='options'.\n\n"
    "CHANNEL-AGNOSTIC FIXES LANDED WHILE WORKING THIS CHANNEL (all in the "
    "shared, un-gated RE_OPT-loop ABOVE/BELOW entry fallback):\n"
    "1. The fallback's original 20-char lookahead window was truncating "
    "the price mid-digit whenever the \"<MONTH> <YEAR>\" expiry suffix "
    "padded out the gap between the strike and \"BUY ABOVE\" -- \"BANKNIFTY "
    "55500 CALL SEP 2026\\nBUY ABOVE 1070\" read entry as 1.0 (just the "
    "leading \"1\" of \"1070\", the rest cut off by the window boundary). "
    "Now searches a wider 60-char slice but only ACCEPTS a match whose "
    "ABOVE/BELOW keyword itself starts within the original 20-char budget "
    "-- the keyword must still be near the strike, but its price is no "
    "longer truncated.\n"
    "2. That widened search, unguarded, then started misreading \"SL "
    "BELOW <price>\" (a stop-loss threshold) as an entry trigger for "
    "Nirmal Bang Official's differently-shaped combo orders -- added an "
    "explicit exclusion for \"SL\"/\"STOP LOSS\" immediately before the "
    "matched ABOVE/BELOW.\n"
    "3. RE_ABOVE_BELOW now also accepts an optional colon (\"ABOVE : "
    "1070\") and a filler \"ONLY\" (\"ABOVE ONLY 1060\") between the "
    "keyword and the price -- both are this channel's own phrasing "
    "variants; verified via full-corpus diff this also recovers one "
    "additional genuine entry in channel 40 (Rochit Singh Stocks, \"Entry "
    "above: 145\").\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch5 "
    "· see git log for commit sha"
)

LIVELONG_HARI = (
    "LIVELONG HARI (channel 17) -- a SEBI-registered broker channel: "
    "clean \"Buy <SYM> above <price> SL <price> t1 <price> t2 <price>\" "
    "cash-equity calls (already well covered by the generic "
    "RE_VERB_FIRST/message-level TARGET/SL fallbacks), option legs, a "
    "once-off monthly equity-basket table (not worth a dedicated parser "
    "at 1 occurrence in the tracked history), and running-price-update "
    "recap spam (\"162====>181.45 HIGH... TARGET DONE AND DUSTED\").\n\n"
    "DOMINANT GAP FOUND: an entry-band shape using \"ABV\" (shorthand for "
    "ABOVE) or the bare word \"RANGE\" as the entry keyword -- \"PAYTM\\n\\n"
    "BUY ABV 1590-91\\n\\nSL 1580\\n\\nTARGET 1600,1610++\", \"EQUITY "
    "INTRADAY\\n\\nWOCKPHARMA \\n\\nBUY RANGE 2200-05\\n\\nSL 2150\\n\\n"
    "Target 2220,2250+\" (cash orders), and the same ABV/RANGE keyword "
    "immediately after an option strike (\"CRUDEOIL 8450 PE\\n\\nBUY abv "
    "262-65\\n\\nSL 240\\n\\nTARGET 280,300+\"). \"ABV\"/\"RANGE\" were "
    "being read as the phantom TICKER itself (23 and 6 occurrences "
    "respectively) since neither word was excluded anywhere. Fixed by "
    "adding both to STOP_WORDS and a new _hari_cash_signal (style='mixed') "
    "that recovers the real single-word ticker from the preceding line -- "
    "anchored to the start of the trigger's own line and rejecting any "
    "multi-word candidate line outright, both added after full-corpus "
    "diff caught two false positives this would otherwise have produced "
    "elsewhere (\"Dnt buy above 7\" in Platinum Research misread \"Dnt\" "
    "as a ticker; \"POSITIONAL TRADE\\nBuy above 400 incase missed it\" in "
    "Stockpro Online collapsed the header into a phantom "
    "\"POSITIONALTRADE\").\n\n"
    "SECOND BUG (option leg): the entry-band's second number (\"262-65\" "
    "means 262 to 265, only the LAST two digits given) was being misread "
    "by the shared RE_RANGE entry-target fallback as the real TARGET "
    "(target=65 instead of the TARGET line's real 280) -- fixed by only "
    "accepting that fallback's second number as a target when it has at "
    "least as many digits as the first.\n\n"
    "CHANNEL-AGNOSTIC FIX LANDED WHILE WORKING THIS CHANNEL (the big "
    "one): a comma-separated multi-target list glued with no space after "
    "the comma (\"TARGET 165,190+\", \"TGT 1600,1610++\") was being read "
    "by the shared _f() number parser as ONE Indian-grouped number, "
    "concatenating unrelated digits into a nonsense target ("
    "\"165,190\"->165190.0 on a sub-200 option premium). Fixed in _f() "
    "itself with a grouping-shape check (see signals.py); confirmed via "
    "full-corpus fingerprint diff this affects only the `target` field "
    "(never entry/SL) across channels 17, 49, 52, and 68, and never "
    "touches a genuine grouped price anywhere in the 82-channel corpus.\n\n"
    "style set to 'mixed'.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch5 "
    "· see git log for commit sha"
)

STOCKBOX_TRADING = (
    "Stockbox Trading (SEBI Registered) (channel 52) -- a broker channel "
    "with clean, already-well-parsed \"Buy <SYM> <strike> CE @<entry>-"
    "<entry2>\\n\\nSl <price>\\n\\nTarget <t1>, <t2>\" option calls and "
    "bare cash-equity calls, plus a daily \"<N>th <Month> Strategy\" "
    "market-structure/OI/PCR data dump (support/resistance zones, "
    "securities-in-ban list) that correctly produces no signal.\n\n"
    "BUG FOUND: the daily strategy dump's \"OI DATA UPDATE:\\n23,500 PE -- "
    "1.14 Cr OI\\n24,000 CE -- 1.20 Cr OI\" table (reporting which strikes "
    "carry the most open interest, not a trade call) was creating a "
    "phantom \"OI 24000 CE\"/\"OI 23700 PE\" trade -- RE_OPT's root regex "
    "bridges the newline and reads the trailing \"OI\" from the END of "
    "the PREVIOUS line as if it were the ticker for the FOLLOWING line's "
    "strike. Fixed by adding \"OI\" to STOP_WORDS (channel-agnostic-safe: "
    "no real ticker is literally \"OI\").\n\n"
    "KNOWN, LEFT UNFIXED: a small number of calls use a genuine two-word "
    "company name whose first word doesn't directly abut the strike "
    "(\"DR REDDY 1370 CE\" -> only \"REDDY 1370 CE\" captured; \"ICICI "
    "BANK 1470 CE\" -> only \"BANK 1470 CE\"), the same structural gap as "
    "Usha's Analysis's month-name case but for an arbitrary company-name "
    "prefix rather than a recognizable expiry token -- no cheap, safe "
    "general fix exists (would need a multi-word-ticker prefix "
    "dictionary); both sampled occurrences already carry blank/partial "
    "data rather than fabricated numbers, so the honest-if-incomplete "
    "status quo was left as-is rather than force a narrow single-case "
    "regex. style set to 'mixed'.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch5 "
    "· see git log for commit sha"
)

EQUIIDEAS = (
    "Equiideas \U0001F43B V/S \U0001F3AF \U0001F402\U0001F3AF (GB) "
    "(channel 10) -- pure live market-commentary/level-calling chatter "
    "(\"57980 CROSSED IN FUTURE CAN SEE 58050/58080/58140/180/220+\", "
    "\"438/42 last resistance in BHEL ABOVE THIS STOCK CAN SEE MOVES "
    "TOWARDS 450/6/64/70+ = NO FRESH BUYING ADVISED\") and sector/stock "
    "narration, explicitly captioned \"NO FRESH BUYING ADVISED\" on most "
    "level calls. Zero SL/TARGET-labelled fields anywhere in the tracked "
    "history (0 messages contain both \"SL\" and \"TGT\"), and the one "
    "\"CMP\" occurrence is unrelated IPO-collapse commentary, not a "
    "trade. All 3 pre-existing trades were phantom rows from a recap "
    "sentence describing an option that had ALREADY moved (\"ASTRAL 1500 "
    "CE = BLASTED FROM 19 TO 77\", \"KHEL SHURU 24150 CE\" -- Hindi "
    "\"khel shuru\" = \"game begins\", not a ticker \"SHURU\") -- the bare "
    "RE_OPT match creates a trade even with entry=None. Classified "
    "style='promo': this channel narrates price action, it never issues "
    "an actionable entry, so promo is the honest and sufficient fix.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch5 "
    "· see git log for commit sha"
)

PLUTUS_ADVISORS = (
    "Learning @ PlutusAdvisors, SEBI Registered Research Analyst (channel "
    "16) -- an educational/macro-data channel: PCR/OI snapshots, "
    "FII/DII participant-wise derivatives data, Instagram/X reel links, "
    "and daily \"Global Morning Macros\" geopolitics/markets digests. No "
    "SL/TGT-labelled trade calls anywhere in the tracked history. All 5 "
    "pre-existing trades were phantom rows from ordinary English words in "
    "macro-commentary prose matching the shared RE_CASH/RE_VERB_FIRST "
    "fallbacks (\"NIFTY\", \"BRING\", \"FAR\", \"BUT\", \"NEED\" -- none a "
    "real ticker or genuine signal). Classified style='promo': this "
    "channel is pure macro/educational content, never an actionable "
    "signal.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch5 "
    "· see git log for commit sha"
)

THETA_GAINERS = (
    "Theta Gainers (channel 64) -- an options-selling algo/education "
    "channel: daily NIFTY/BANKNIFTY support-resistance/PCR commentary "
    "(\"23200 is support and next support is 23000\", \"PCR is 0.95 "
    "around ATM\"), running Cosmic-broker algo P&L updates (\"3.15 pm "
    "trade closed for today at 2000 per lot profit\"), event/workshop "
    "promos, and crypto-exchange referral spam (\"Ab crypto futures INR "
    "mein trade karo... UPI se INSTANT deposit\"). No stock/option ticker "
    "with an entry price is ever posted -- the channel narrates index "
    "levels and its own algo's aggregate P&L, never an individual "
    "actionable call a reader could replicate. 0 pre-existing trades "
    "(correctly). Classified style='promo'.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch5 "
    "· see git log for commit sha"
)


def set_styles(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    updates = {
        68: ('mixed', USHA_ANALYSIS),
        63: ('promo', THEDOJI),
        41: ('options', SAIRAM_STOCKS),
        17: ('mixed', LIVELONG_HARI),
        52: ('mixed', STOCKBOX_TRADING),
        10: ('promo', EQUIIDEAS),
        16: ('promo', PLUTUS_ADVISORS),
        64: ('promo', THETA_GAINERS),
    }
    for channel_id, (style, notes) in updates.items():
        Channel.objects.filter(id=channel_id).update(style=style, style_notes=notes)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('traderacker', '0020_batch4_style_notes'),
    ]

    operations = [
        migrations.RunPython(set_styles, noop),
    ]
