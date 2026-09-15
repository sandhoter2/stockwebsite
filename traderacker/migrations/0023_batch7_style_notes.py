# Sets Channel.style / style_notes for channels covered by the "batch7"
# full-history specialist pass (docs/AGENT_HANDOFF.md pattern). This first
# slice covers Trading With Ca Abhay, Stock Gainers, and ROCHIT SINGH
# STOCKS -- the remaining batch7 channels are added by a later migration
# in the same series as they're completed. Data-only migration -- safely
# no-ops if a channel doesn't exist yet (fresh/test DB), and is idempotent
# (re-running it just overwrites with the same values).
from django.db import migrations

TRADING_WITH_CA_ABHAY = (
    "Trading With Ca Abhay | SEBI RE (channel 66) -- an index-options "
    "tipster: NIFTY/BANKNIFTY/SENSEX CE/PE calls posted as a strike "
    "header line, then the entry trigger a couple of lines below, then "
    "the SAME leg reposted many times over the life of the trade as a "
    "bare \"<symbol>\\n<price>\" running LTP ticker while it's live.\n\n"
    "DOMINANT SHAPE: \"SENSEX 78100 PE\\n\\nNEAR 330\\n\\nTGT open\\n\\n"
    "Sl follow\", \"NIFTY 24300 CE\\n\\nNear 140\\n\\nTGT open\\n\\nSl "
    "follow\" -- entry keyword is \"NEAR <price>\" directly after the "
    "strike (new RE_NEAR_ENTRY, tightly windowed to <20 chars right after "
    "the strike match -- NOT folded into RE_ABOVE_BELOW's own unwindowed "
    "use site, which would then read unrelated \"...trading near "
    "<price>\" market commentary elsewhere in other channels' messages as "
    "an entry trigger). style='auto' (the channel's dominant order shape "
    "is generic enough that no channel-specific style gate was needed "
    "beyond the NEAR-entry regex itself).\n\n"
    "TRAPS FOUND THE HARD WAY:\n"
    "1. CHANNEL-AGNOSTIC BUG (biggest single fix in this pass): the "
    "running-LTP repost \"<symbol>\\n<price>\" has no keyword to "
    "distinguish it from a fresh minimal-shape entry, so RE_OPT's own "
    "optional trailing-NUM fallback read every repost as a DISTINCT trade "
    "under (channel, trade, entry) dedup -- 124 occurrences, producing "
    "10+ phantom duplicate Open rows per real call (42 real Open trades "
    "inflated to well over 100). Fixed with a new whole-message fullmatch "
    "guard, RE_OPT_BARE_PRICE_REPOST, checked before any other parsing in "
    "parse_message -- verified as a fullmatch (not a span exclusion) so "
    "it can never suppress a real entry sharing a strike with some other "
    "channel's genuine minimal-shape order elsewhere in the text. This "
    "channel's own repost never has trailing decoration, but the same "
    "bug/fix pattern recurred for Stock Gainers (48, plain-number style) "
    "and ROCHIT SINGH STOCKS (40, emoji-decorated) -- see their notes.\n"
    "2. \"NEAR\" is common prose elsewhere (Ritvi Taneja, Nasdaq Masters, "
    "PL Technical Research, ...) but never sits directly after a "
    "strike+CE/PE token in any OTHER channel within a 20-char window -- "
    "verified empirically across the full 82-channel corpus before "
    "keeping the window that tight.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch7 "
    "· see git log for commit sha"
)

STOCK_GAINERS = (
    "Stock Gainers (channel 48) -- an index/commodity-options tipster "
    "with a dated header shape: \"<INDEX> <DAY> <MON> <STRIKE> CE/PE\", "
    "entry given either as \"Range @ <price>\" (existing RE_SMS_RANGE_ENTRY) "
    "or \"ABOVE :- <price>\" (this pass's addition), then reposted live as "
    "a bare LTP ticker in BOTH directions -- symbol-then-price like "
    "channel 66, and also a mirror-image price-then-symbol shape unique "
    "to this channel. style='options' (pre-existing from ingestion; no "
    "style_notes recorded until now).\n\n"
    "DOMINANT SHAPE: header with a date infix breaks RE_OPT's own root "
    "match, so the -1 special-case block (style=='options' + a date-infixed "
    "header) is the only path that sees these messages at all. Extended "
    "this pass to also accept \"ABOVE :- <price>\" (RE_ABOVE_BELOW, tried "
    "only after RE_SMS_RANGE_ENTRY so STOCK MARKET SCHOOL's own \"Range\" "
    "convention stays untouched) as an alternate entry trigger alongside "
    "the existing \"Range @\" shape.\n\n"
    "TRAPS FOUND THE HARD WAY:\n"
    "1. Without the ABOVE fallback, the real dated-header entry message "
    "was invisible to every regex in the file, while a LATER reversed-"
    "order recap of the SAME leg with no date token (\"145\\n\\nNIFTY "
    "23550 PE\") matched plain RE_OPT with no entry, producing a blank-"
    "valued phantom trade instead of the real, priced one.\n"
    "2. Mirror-image repost, bare LTP FIRST then symbol (\"155\\u2665\\ufe0f"
    "\\n\\n\\nNIFTY 23550 PE\") -- RE_OPT still matches the trailing "
    "symbol+strike with nothing following it, producing a second, blank-"
    "valued phantom Trade alongside the real priced one from the earlier "
    "dated header. Fixed with RE_OPT_BARE_PRICE_REPOST_REV, the reversed "
    "counterpart of channel 66's repost guard, tolerating up to 15 chars "
    "of trailing junk (emoji) after the leading number -- verified unique "
    "to this channel across the full 82-channel corpus (21 occurrences).\n"
    "3. Also shares the \"ABOVE :- \" colon-dash entry spelling with "
    "ROCHIT SINGH STOCKS (40) and two other channels (15, 55) -- one "
    "shared regex change covers all four (RE_ABOVE_BELOW's colon-dash "
    "tolerance), verified unique to exactly those 4 channels.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch7 "
    "· see git log for commit sha"
)

ROCHIT_SINGH_STOCKS = (
    "ROCHIT SINGH STOCKS (channel 40) -- an index-options tipster very "
    "close in house style to Trading With Ca Abhay (66): NIFTY/SENSEX/"
    "BANKNIFTY CE/PE calls with \"BUY <symbol>\\n\\nABOVE - <price>\" or "
    "\"<symbol>\\n\\nNear <price>\" entries, then reposted live as a bare "
    "LTP ticker while the call is open, this channel's own reposts "
    "decorated with trailing emoji (\"\\U0001F3AF\\U0001F3AF\\U0001F4B8\\U0001F4B8\", "
    "\"\\U0001F525\\U0001F525\\u2705\", ...) rather than a plain bare number. "
    "style='auto'.\n\n"
    "DOMINANT SHAPE: \"BUY NIFTY 24100 CE\\n\\nABOVE - 140\\n\\nTARGET "
    "\\U0001F3AF - 150,160,170++++\\n\\nSTOP LOSS - prime\" then reposted as "
    "\"BUY NIFTY 24100 CE\\n140\\U0001F3AF\\U0001F3AF\\U0001F4B8\\U0001F4B8\", "
    "\"...142...\", \"...144...\" etc for every price tick while live. Also "
    "uses \"ABOVE :- <price>\" (shared with Stock Gainers/48, see its "
    "notes) and occasionally \"ABOVE >500\" with a decorative arrow "
    "instead of a dash.\n\n"
    "TRAPS FOUND THE HARD WAY:\n"
    "1. Same channel-agnostic bare-price-repost bug as channel 66, but "
    "this channel's repost always carries trailing emoji/junk after the "
    "price, which the ORIGINAL fix (channel 66/48 only, requiring \\s*\\Z "
    "immediately after the digits) did not catch -- 150 occurrences fell "
    "through to RE_OPT's fallback and produced 100+ phantom duplicate "
    "Open rows (144 Open trades before this fix, 22 after). Fixed by "
    "widening RE_OPT_BARE_PRICE_REPOST to tolerate up to 15 chars of "
    "trailing non-digit junk, mirroring RE_OPT_BARE_PRICE_REPOST_REV's "
    "own tolerance. Re-verified safe across the full 82-channel corpus "
    "with the wider match: it also newly (and correctly) catches the same "
    "emoji/word-decorated repost shape in channels 6, 15, 17, 23, 32, 39 "
    "(1-8 occurrences each, spot-checked against source text) -- those "
    "channels' Trade counts drop by a handful of pre-existing phantom "
    "rows too (6: 488->486, 17: 188->180, 39: 268->267), with the full "
    "163-test suite still green.\n"
    "2. A further variant prefixes the repost price with a rupee glyph "
    "(\"\\u20b9 150 \\U0001F525\\U0001F525\\u2705\") -- 3 occurrences, unique to "
    "this channel, added as an optional leading glyph to the same regex.\n"
    "3. \"ABOVE >500\" (decorative arrow instead of dash) -- 2 "
    "occurrences, unique to this channel -- added \">\" alongside the "
    "existing dash tolerance in RE_ABOVE_BELOW.\n"
    "4. LEFT DELIBERATELY UNFIXED (residual, ~6 blank-entry duplicate "
    "rows remain): a handful of exit/celebration follow-ups with NO "
    "digit at all (\"NIFTY 24100 CE\\nProfit book karna hai...\", "
    "\"SENSEX 75500 PE\\nBoom \\U0001F4A5\") still mint a blank-entry phantom "
    "row alongside the real priced one for the same symbol. Tried a "
    "generic \"<symbol>\\n<non-numeric text>\" whole-message suppression "
    "and rejected it -- across the corpus this shape also matches GENUINE "
    "entry signals in other channels (channel 17's \"CRUDEOIL 9700 CE\\n"
    "Day high break out\", channel 72's \"SENSEX 78700 CE\\nBuy\"), so it "
    "is not safely distinguishable by shape alone; would need per-phrase "
    "matching, which is fragile and not attempted here. Also unfixed: a "
    "bare \"BUY <price>\" entry trigger with no ABOVE/NEAR keyword (\"NIFTY "
    "24300 PE\\n\\nBUY 160\\n\\nTGT paid\", 4 occurrences) -- a generic "
    "\"BUY <price>\" regex was tried and rejected as far too broad (612 "
    "unrelated hits in channel 71 alone, plus promo/rating/FII-DII noise "
    "in a dozen other channels).\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch7 "
    "· see git log for commit sha"
)


def set_styles(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    updates = {
        66: ('auto', TRADING_WITH_CA_ABHAY),
        48: ('options', STOCK_GAINERS),
        40: ('auto', ROCHIT_SINGH_STOCKS),
    }
    for channel_id, (style, notes) in updates.items():
        Channel.objects.filter(id=channel_id).update(style=style, style_notes=notes)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('traderacker', '0022_batch6_style_notes'),
    ]

    operations = [
        migrations.RunPython(set_styles, noop),
    ]
