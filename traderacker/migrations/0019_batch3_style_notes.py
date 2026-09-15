# Sets Channel.style / style_notes for the 8 channels covered by the
# "batch3" full-history specialist pass (docs/AGENT_HANDOFF.md pattern):
# Stock Gainers (SEBI Registered), Nivisha Verma (Bnf_unicorn), Ritvi
# Taneja (Passionate Trader), Samco, Trading Ideas By Darshan,
# Mystocks.in, FINANCIAL SARTHIS, Nasdaq masters. Data-only migration —
# safely no-ops if a channel doesn't exist yet (fresh/test DB), and is
# idempotent (re-running it just overwrites with the same values).
from django.db import migrations

STOCK_GAINERS = (
    "SEBI-registered tipster channel (\"Stock Gainers (SEBI REGISTERED)\") "
    "posting cash-equity and index-option intraday/swing calls in a "
    "casual, emoji-heavy style, plus a recurring \"Live Analysis of "
    "<date>\" end-of-day digest recap and PRIME-group promo pings. 1950 "
    "tracked messages.\n\n"
    "DOMINANT SHAPES (1575 of 1950 messages were unparsed before this "
    "pass, found by checking coverage rather than correctness on what "
    "already matched):\n"
    "1. \"<SYMBOL>\\n\\nCMP <price>\\n\\nSupport <price>\\n\\n\\nFor "
    "<range>\" forward entry call, e.g. \"DIAMOND POWER\\n\\nCMP 356\\n\\n"
    "Support 340\\n\\n\\nFor 385-410\" — new RE_STOCKGAINERS_ENTRY, entry="
    "CMP, stop_loss=Support, target=first number of the \"For\" range. "
    "Tolerates exactly one extra commentary line between labels (\"Support "
    "only 130\", \"Can Accumulate till 1000\").\n"
    "2. \"<SYMBOL>\\n\\n<N> to <M>\" retrospective recap, e.g. \"Astra "
    "Micro\\n\\n1440 to 1480\" — new RE_STOCKGAINERS_RECAP, shared with "
    "Ritvi Taneja (see below). Requires the symbol ALONE on its own line "
    "followed by one-or-more newlines then the price pair — this is what "
    "keeps it from ever matching the daily digest post, which crams "
    "\"SYMBOL price TO price\" onto a single line per stock with no "
    "blank-line gap (verified empirically: 0 digest matches across the "
    "full history). Recorded Open with entry/target filled, never "
    "fabricated Closed (this codebase's exit machinery can't confirm a "
    "same-message close — see Short To Mid Term's style_notes from an "
    "earlier pass for the same limitation, same reasoning).\n\n"
    "TRAPS: a small denylist (STOCKGAINERS_DENY) rejects commentary/"
    "header words that would otherwise ride along as a phantom \"symbol\" "
    "ahead of shape 2's blank-line-then-price pattern (\"Breakout\", "
    "\"Locked\", \"PERFECT SETUP\", \"BTST\"/\"Equity Pick\"/etc. post-"
    "type headers). \"FUT\"/\"OPTION\"/\"KEEP\"/\"RADAR\" also added to "
    "the GLOBAL STOP_WORDS set — generic trading-jargon/phrase words that "
    "were producing bogus phantom tickers here (and, for FUT/OPTION, in "
    "Stockizen Research and 𝑵𝒂𝒔𝒅𝒂𝒒 𝒎𝒂𝒔𝒕𝒆𝒓𝒔 too) via the shared RE_CASH/"
    "RE_VERB_FIRST fallbacks.\n\n"
    "DELIBERATELY UNPARSED: the daily \"Live Analysis of <date>\" digest "
    "(pure recap of calls already tracked from their original signal "
    "message — parsing it would mint dozens of phantom duplicates); PRIME "
    "-group join/renewal pings; pure market commentary with no symbol+"
    "price.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch3 "
    "(channel/batch3) · batch3 specialist pass"
)

NIVISHA_VERMA = (
    "Nivisha Verma / Bnf_unicorn — cash-equity and index-option swing "
    "calls delivered as a short symbol line followed by a \"✅\"-bulleted "
    "list of chart commentary, plus occasional X/Twitter cross-posts and "
    "Hindi festival greetings. 1940 tracked messages, only 7 trades "
    "existed before this pass.\n\n"
    "DOMINANT SHAPE: \"<SYMBOL>\\n✅<commentary>\\n✅Breakout above "
    "<price>...\\n✅Support ...<price>\\n✅Target(s) ...<price>\\n✅Keep on "
    "radar\", e.g. \"PIDILITE IND\\n✅Breakout above 3280+ possible\\n✅"
    "Strong chart\\n✅Large cap getting strong\\n✅After breakout support "
    "will be 3160/3050\\n✅Target 3350/3475/3600++\\n✅Keep on radar\". New "
    "_bnfunicorn_bullet_signal (shared with Ritvi Taneja's \"➡\"-bulleted "
    "variant, see below) requires an explicit above/breakout-level entry "
    "trigger — a bare support+target call with no stated entry (e.g. "
    "\"AEROFLEX\\n🤝Promising chart breakout\\n✅Strong weekly close\\n✅"
    "Support 160 & 147\\n✅looks good for 190/200+\\n✅Keep on radar\") is "
    "deliberately left unparsed rather than guessing an entry price.\n\n"
    "TRAP: the symbol-line candidate is capped at 3 words and validated "
    "against STOP_WORDS so an ordinary sentence mentioning a ticker "
    "mid-clause (\"Place an alert in CENTRAL BANK above 42.\") is never "
    "mistaken for a symbol line.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch3 "
    "(channel/batch3) · batch3 specialist pass"
)

RITVI_TANEJA = (
    "Ritvi Taneja / Passionate Trader — Hinglish cash-equity and index-"
    "option swing/intraday calls. 1927 tracked messages, only 10 trades "
    "existed before this pass (previously documented in "
    "docs/AGENT_HANDOFF.md §5 as the next channel in queue).\n\n"
    "THREE SHAPES, found by checking coverage rather than correctness on "
    "what already matched:\n"
    "1. \"➡\"-bulleted breakout call — same structure and parser as "
    "Nivisha Verma/Bnf_unicorn above (_bnfunicorn_bullet_signal, "
    "generalized to accept either bullet marker), e.g. \"HINDZINC\\n➡ "
    "Re-creating Pole & Flag Pattern\\n➡ Breakout possible above 700\\n➡ "
    "Support near 630\\n➡ Keep on radar\".\n"
    "2. \"<SYMBOL>\\n\\n<N> to <M>\" retrospective recap — same "
    "RE_STOCKGAINERS_RECAP as Stock Gainers above, e.g. \"Adani ports\\n"
    "1728 to 1785\", \"BLS \\n372 to 396\" (this channel's variant is "
    "sometimes separated by only a single newline, not a full blank line "
    "— the shared regex now tolerates either). TRAP found here "
    "specifically: a two-line \"<SYMBOL>\\n<commentary>\\n\\n<N> to <M>\" "
    "call (e.g. \"WEBELSOLAR\\nAgain upper circuit\\n\\n590 to "
    "1421++\") would otherwise let the commentary line win the \"nearest "
    "line above\" heuristic over the real symbol two lines up — "
    "\"AGAIN\"/\"TREND\"/\"UPPER\"/\"AMAZING\" added to the shared "
    "STOCKGAINERS_DENY list to close this.\n"
    "3. \"<SYMBOL> <PRICE>\" alone on the first line, with a \"Support\" "
    "figure and a \"Can hit <ladder>\"/\"Target\"/\"Towards\" figure "
    "elsewhere in the message — new _symline_support_signal, e.g. \"SBIN "
    "1011\\nSupport 992\\n\\nAvg 1000-995\\n\\nCan hit "
    "1025/1038/1050\\n\\nWeak below 992 closing\". Also fires (correctly) "
    "for Stock Gainers and Bnf_unicorn's own \"<SYMBOL> <PRICE>\" first-"
    "line convention — verified 0 matches on any other 'mixed' channel.\n\n"
    "DELIBERATELY UNPARSED: closes are Hinglish prose with NO rupee "
    "figure (\"Jackpot ho gya aaj ka\", \"Booking profit today\", "
    "\"Trailing my stoploss to 210 now.\" — that last one moves the SL, "
    "not a loss) — per this codebase's realized-truthfulness rule, these "
    "stay Open with no fabricated ₹ amount, same as documented for this "
    "channel in §5 before this pass began.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch3 "
    "(channel/batch3) · batch3 specialist pass"
)

SAMCO = (
    "Samco Securities' formal SEBI-RA \"RECOMMENDATION ALERT\" broker "
    "template — cash, futures and (dominant) options intraday/positional "
    "calls, plus recurring IPO/webinar/global-investing promo. 1927 "
    "tracked messages. This channel's 144 pre-existing trades were "
    "PHANTOMS, not real coverage — garbage roots like \"MAR 23500 CE\" "
    "torn out of a glued option ticker (\"AUBANK25DEC980PE\") by the "
    "generic RE_VERB_FIRST/RE_CASH/RE_OPT fallbacks, which have no way to "
    "bridge a root ticker separated from its strike by a compact "
    "\"<DD><MON>\" expiry token.\n\n"
    "Every RECOMMENDATION ALERT carries the SAME data in two independent "
    "places, both now parsed (their (channel, trade, entry) upsert key "
    "naturally collapses a double-match into one Trade row):\n"
    "1. The structured field block: \"Stock Name: Pfizer Limited\\n"
    "Symbol: PFIZER\\nRating: Buy 🟢\\nCMP: ₹4130\\nStop loss: ₹3890\\n"
    "Target: ₹4545\\nDuration: 5-10 Days...\" — new _samco_block_signal. "
    "\"Symbol:\" is always the real ticker (unlike \"Stock Name:\", the "
    "full company name, sometimes blank for an index leg). 829 of 1927 "
    "messages match. Deliberately rejects the rare (2 of 1927) multi-leg "
    "straddle/strangle alert whose \"Symbol:\" line embeds a second BUY/"
    "SELL leg and its own CMP — that alert's Stop loss/Target are a total "
    "₹ P&L across all four legs, not a per-share price.\n"
    "2. The trailing \"Note: Buy <SYM> at <price> SL <sl> TGT <tgt>\" "
    "one-liner (or \"...at CMP <price>...\", \"...at CMP of Rs.<price> "
    "with SL of Rs.<sl>\" for the no-Target long-duration picks) — new "
    "_samco_note_signal. Runs BEFORE the generic verb-first/cash "
    "fallbacks (moved to step 1g) and claims the root via option_roots: "
    "a spaced glued-expiry symbol in the Note line (\"Buy AUBANK "
    "25DEC980PE at 10.5...\") would otherwise already be mis-read as a "
    "bogus cash order \"AUBANK\" @ 25 (the expiry token's own \"25\") "
    "before this shape ever got a turn.\n"
    "3. Both normalize the glued-expiry option ticker "
    "(\"AUBANK25DEC980PE\", spaced or not) down to this codebase's "
    "\"ROOT STRIKE CE/PE\" convention via _parse_samco_symbol, reusing "
    "the DDMMM expiry shape. The rare weekly-numeric-expiry format with "
    "NO letter month code (\"NIFTY2540323300CE\") doesn't match and is "
    "deliberately left as an ugly-but-honest literal symbol rather than "
    "guessing where the strike starts — a >6-digit-strike guard on the "
    "shared RE_OPT/RE_OPT_INDEX_CI (see below) stops that same symbol "
    "from ALSO spawning a blank second row under the generic option "
    "regex.\n\n"
    "TWO CHANNEL-AGNOSTIC BUG FIXES found while tracing this channel's "
    "phantoms, both in the shared RE_OPT loop (step 1) rather than "
    "style-gated, since the bug reproduces for any channel with this "
    "digit-shape: (a) a \"root\" that is literally a 3-letter month "
    "abbreviation glued to or followed by digits (\"APR12275\", \"MAR "
    "49500\") is never a real ticker — it's RE_OPT backtracking onto the "
    "DDMMM expiry token's own letters when it can't bridge the digit-"
    "then-letter gap to the real root; (b) a >6-digit strike is never "
    "real (even the highest index strikes are ≤6 figures) — it's the "
    "weekly-numeric-expiry symbol read whole. Verified via full old-vs-"
    "new diff: both fixes ALSO correctly remove 3 pre-existing phantom "
    "trades from Angel One Research (channel 3) and NIRMAL BANG OFFICIAL "
    "(channel 26) that predate this pass, with zero other changes to "
    "either channel's history.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch3 "
    "(channel/batch3) · batch3 specialist pass"
)

TRADING_IDEAS_DARSHAN = (
    "Trading Ideas By Darshan — mostly Vedic/financial-astrology "
    "commentary (\"Today's Planetary Aspects\", Nakshatra remedies) with "
    "a genuine minority of index-option and cash-equity calls in a "
    "consistent house style. 1903 tracked messages, 0 trades existed "
    "before this pass.\n\n"
    "TWO SHAPES:\n"
    "1. Forward option order: \"Nifty 26100 Ce (13 Jan Expiry)\\nCmp "
    "151\\nTarget Open\\nStoploss 120\\n\\n*Keep Proper Risk "
    "Management...\" — new _darshan_option_entry_signal. \"Target Open\" "
    "means no stated numeric target and is kept blank rather than "
    "guessed; Cmp is the entry, Stoploss self-explanatory.\n"
    "2. Retrospective recap: \"Sail from 129.3 to 141\", \"Sensex 74900 "
    "Ce From 5 to 160\" — new _darshan_recap_signal, sharing the same "
    "underlying \"<name> from <N> to <M>\" pattern for both cash/index "
    "and option legs (a trailing \"<strike> CE|PE\" on the symbol "
    "candidate is normalized into this codebase's usual option-trade "
    "string). Direction for an option leg comes from CE/PE itself, never "
    "guessed from the price move; for cash/index, from which side of the "
    "range is higher (same convention as Stocky Mind's RE_STOCKY_RECAP "
    "from an earlier pass).\n\n"
    "TRAP: DARSHAN_VERB_DENY rejects ordinary market-commentary verbs "
    "(\"rallied\", \"surged\", \"moved\", \"breakout\", \"massive\") that "
    "would otherwise ride along as part of a multi-word symbol candidate "
    "before \"from\" — found via a genuine false positive on Stockpro "
    "Online's \"TANLA Massive breakout\\nFrom 567 to 628\" (this shape's "
    "\"from\" recap pattern is channel-agnostic and picked up 5 harmless, "
    "correct additional calls there as a verified-safe side effect, e.g. "
    "\"Gsp crop from 445 to 591\", \"BLISS From 325 to 573\").\n\n"
    "KNOWN RESIDUAL LIMITATION (documented, not fixed — ~14 of ~271 "
    "signals): step 1's generic RE_OPT/RE_OPT_INDEX_CI run unconditionally "
    "before this channel's own shapes get a turn and sometimes create a "
    "blank-entry placeholder under a truncated root (\"NIFTY 14000 CE\" "
    "instead of \"MIDCAP NIFTY 14000 CE\") that this pass's dedup-and-"
    "patch logic doesn't catch when the truncated root differs by more "
    "than the trade suffix; and \"Ce\\nSL Triggered\"/\"Ce\\nBack at "
    "Cost\" close-out-only messages get misread as a fresh blank order by "
    "the same unconditional step. Both pre-existing classes of bug, not "
    "introduced by this pass.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch3 "
    "(channel/batch3) · batch3 specialist pass"
)

MYSTOCKS_IN = (
    "Mystocks.in — Hinglish cash-equity swing/intraday calls, almost "
    "entirely in the existing channel-agnostic \"Bought #<SYM> <price>\" "
    "hashtag-ticker shape (RE_VISHAL_BOUGHT, added for Swing Trader "
    "Vishal in an earlier pass). 1897 tracked messages; only 5 trades "
    "existed before this pass because Channel.style was 'auto' (that "
    "shape is style-gated to 'cash') — setting style='cash' alone takes "
    "coverage from 5 to 154 distinct trades, no new regex needed.\n\n"
    "CHANNEL-AGNOSTIC BUG FIX found while auditing SL/target quality "
    "here: \"SL 1%\" / \"Target 4-6%\" are risk-sizing PERCENTAGES, not "
    "absolute prices (e.g. \"Bought #MVELECTRO 615\\n\\nSL 1%\\n\\nTarget "
    "4-6%\"), but RE_SUPPORT/RE_TARGET (and their _MIXED variants) were "
    "reading the bare number as if it were a price (stop_loss=1.0 on a "
    "₹615 entry). Fixed with a negative lookahead (NUM_NOT_PCT) rejecting "
    "a number immediately followed by \"%\" or \"-<N>%\" — verified "
    "empirically this excludes 73 stray matches across the full 82-"
    "channel history (45 in this channel alone) and creates zero new "
    "exclusions elsewhere.\n\n"
    "DELIBERATELY UNPARSED: target ladders with no \"Target\"/\"TGT\" "
    "keyword at all (e.g. \"1200/1250++\" stated bare after a support "
    "line) stay blank rather than guessed; #hashtag stock mentions with "
    "no stated price (watchlist chatter) correctly produce nothing.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch3 "
    "(channel/batch3) · batch3 specialist pass"
)

FINANCIAL_SARTHIS = (
    "𝐅𝐈𝐍𝐀𝐍𝐂𝐈𝐀𝐋 𝐒𝐀𝐑𝐓𝐇𝐈𝐒 — Nifty/BankNifty index-option and occasional "
    "cash/futures intraday calls, heavily interleaved with market "
    "commentary discussing \"<strike> PUT WRITER\"/\"<strike> CALL "
    "WRITER\" positioning (not this channel's own trade calls). 1897 "
    "tracked messages. ~90 messages produced signals before this pass "
    "(via the shared uppercase-only option/cash regexes); roughly half "
    "this channel's real calls write ce/pe/put/call in lower or mixed "
    "case, invisible to every case-sensitive option regex in this file "
    "by design.\n\n"
    "NEW SHAPE: a case-insensitive option-order parser (new "
    "RE_FINSARTHI_OPT / _finsarthi_option_signal) that requires the FULL "
    "\"<root> <strike> CE/PE/CALL/PUT ... SL <n> ... TARGET/TGT <n>\" "
    "structure in one match, not just a bare \"<number> ce/pe\" — this is "
    "what excludes the constant \"put writer\"/\"call writer\" commentary "
    "(\"Bankex 65100 put from 12 to 100\", \"24200 put writer are still "
    "there\") without a separate WRITER-specific exclusion. Runs at step "
    "1h (before the generic verb-first/cash fallbacks) and claims "
    "option_roots so a lowercase symbol like \"Bank nifty 55000 ce\" "
    "isn't first mis-read by generic RE_OPT_INDEX_CI as a truncated "
    "\"NIFTY 55000 CE\" placeholder (patched in place when it is).\n\n"
    "VERIFIED SIDE EFFECTS elsewhere (both harmless/beneficial, found via "
    "full-corpus check before landing): Angel One Research's \"BANKNIFTY "
    "MAR 49500 CE @ 361-365 SL 407 TGT 300\" now gets its real entry "
    "(361) via this shape's multi-word root capture, instead of nothing; "
    "4 already-mostly-covered Ashika Calls messages gain a same-(channel,"
    "trade) blank-entry duplicate of a trade Ashika's own parser already "
    "captured correctly (no new row).\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch3 "
    "(channel/batch3) · batch3 specialist pass"
)

NASDAQ_MASTERS = (
    "𝑵𝒂𝒔𝒅𝒂𝒒 𝒎𝒂𝒔𝒕𝒆𝒓𝒔 — forex/gold/crypto (XAUUSD, GOLD, BTCUSD) signal "
    "channel: a BUY/SELL + entry price, then a stream of \"TP<n> HIT\" "
    "progress-update reposts and a final close-out, plus recurring "
    "account-management solicitation. 1891 tracked messages. 125 trades "
    "already existed via the shared uppercase-only RE_VERB_FIRST/"
    "RE_BUYSELL, but roughly half this channel's real calls write buy/"
    "sell in lower or mixed case (\"XAUUSD sell 4335+4340\") or use a "
    "\"CAN BUY WITH\"/\"CAN SELL WITH\" phrasing (\"*GOLD CAN BUY WITH "
    "4402\").\n\n"
    "NEW SHAPE: RE_NASDAQMASTERS_FX / _nasdaqmasters_fx_signal, case-"
    "insensitive on BUY/SELL. Making the SHARED RE_BUYSELL itself case-"
    "insensitive was tried and rejected — a full-corpus check found real "
    "false positives elsewhere entirely outside this batch (a news "
    "headline's \"BIG sell-off in both the indexes...\", a bulk-deal "
    "report's \"...WORTHY DIS[COUNT]...BLW Buy\", an RBI policy note's "
    "\"...INR buy...\"). Scoped instead to a small enumerated instrument "
    "set this channel actually trades (XAUUSD/GOLD/BTCUSD/SILVER/XAGUSD/"
    "EURUSD/GBPUSD/USDJPY) — the same convention RE_OPT_INDEX_CI already "
    "uses for index roots — verified empirically 0 matches on any other "
    "channel's full history. A \"+\"-joined dual price "
    "(\"4335+4340\") keeps only the first number as the entry, same "
    "\"never average or guess\" convention as the ladder shapes elsewhere "
    "in this file. 125 -> 247 distinct (trade, entry) pairs.\n\n"
    "DELIBERATELY UNPARSED: the constant \"TP<n> HIT DONE <n>+ PIPS\" "
    "progress/close-out reposts (correctly not a fresh entry); account-"
    "management solicitation and deposit/profit/withdrawal screenshots "
    "(pure promo, not a signal).\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch3 "
    "(channel/batch3) · batch3 specialist pass"
)


def set_styles(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    updates = [
        ('Stock Gainers (SEBI Registered)', 'mixed', STOCK_GAINERS),
        ('Nivisha Verma (Bnf_unicorn)', 'mixed', NIVISHA_VERMA),
        ('Ritvi Taneja (Passionate Trader)', 'mixed', RITVI_TANEJA),
        ('Samco', 'mixed', SAMCO),
        ('Trading Ideas By Darshan', 'mixed', TRADING_IDEAS_DARSHAN),
        ('Mystocks.in', 'cash', MYSTOCKS_IN),
        ('𝐅𝐈𝐍𝐀𝐍𝐂𝐈𝐀𝐋 𝐒𝐀𝐑𝐓𝐇𝐈𝐒', 'mixed', FINANCIAL_SARTHIS),
        ('𝑵𝒂𝒔𝒅𝒂𝒒 𝒎𝒂𝒔𝒕𝒆𝒓𝒔', 'mixed', NASDAQ_MASTERS),
    ]
    for name, style, notes in updates:
        Channel.objects.filter(name=name).update(style=style, style_notes=notes)


def unset_styles(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    names = [
        'Stock Gainers (SEBI Registered)',
        'Nivisha Verma (Bnf_unicorn)',
        'Ritvi Taneja (Passionate Trader)',
        'Samco',
        'Trading Ideas By Darshan',
        'Mystocks.in',
        '𝐅𝐈𝐍𝐀𝐍𝐂𝐈𝐀𝐋 𝐒𝐀𝐑𝐓𝐇𝐈𝐒',
        '𝑵𝒂𝒔𝒅𝒂𝒒 𝒎𝒂𝒔𝒕𝒆𝒓𝒔',
    ]
    Channel.objects.filter(name__in=names).update(style='auto', style_notes='')


class Migration(migrations.Migration):

    dependencies = [
        ('traderacker', '0018_batch2_style_notes'),
    ]

    operations = [
        migrations.RunPython(set_styles, unset_styles),
    ]
