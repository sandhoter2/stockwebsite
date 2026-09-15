# Sets Channel.style / style_notes for Nrj finance (channel 29), the
# second slice of the batch7 8-channel assignment (docs/AGENT_HANDOFF.md
# pattern). Data-only migration -- safely no-ops if the channel doesn't
# exist yet (fresh/test DB), and is idempotent (re-running it just
# overwrites with the same value).
from django.db import migrations

NRJ_FINANCE = (
    "Nrj finance (channel 29) -- an index/commodity-options tipster "
    "(NIFTY/SENSEX/CRUDEOIL/SILVER/GOLD CE/PE) whose ENTIRE dominant "
    "message shape -- symbol, strike, keywords, and prices -- is written "
    "in Unicode \"Mathematical Bold\"/\"Sans-Serif Bold\" compatibility "
    "characters (e.g. \"\U0001D5D5\U0001D604\U0001D604 \U0001D5F0\U0001D5A6\U0001D5F1\U0001D5F2\U0001D5A2\U0001D5F8 \U0001D7EF\U0001D7EF\U0001D7EE\U0001D7EE \U0001D400\U0001D400\" for "
    "\"Buy Sensex 75800 CC\"-shaped text) rather than plain ASCII. style="
    "'auto' (the underlying shape, once decoded, is the same generic "
    "\"BUY <SYMBOL> <strike> <CE/PE> (<date> Ex)\" / \"ABOVE:- <price>\" "
    "order already understood by RE_OPT + RE_ABOVE_BELOW; no channel-"
    "specific regex needed beyond the font decoding).\n\n"
    "DOMINANT SHAPE: \"Buy CRUDEOIL 9800 PE (14 MAY Ex)\\n\\nABOVE:-320//325"
    "\\n\\nTARGET:-YOUR\\n\\nSL:-YOUR\", i.e. an explicit price-agnostic "
    "\"YOUR\" for target/SL (never a number -- correctly left unset by the "
    "existing generic path, not a bug), and a double-slash-separated price "
    "pair after ABOVE (\"320//325\", first number kept as entry, same "
    "never-average-a-ladder convention as elsewhere in this file).\n\n"
    "CHANNEL-AGNOSTIC BUG FIXED THIS PASS: none of this file's ASCII-only "
    "regexes ever matched this channel's stylized font, so it looked "
    "entirely parser-blind (0 trades from 1,141 messages) for a purely "
    "cosmetic reason. Fixed with a single `unicodedata.normalize('NFKC', "
    "text)` at the top of `parse_message` (see the comment there for the "
    "full corpus-wide verification) -- this alone took the channel from 0 "
    "to 70 Open trades with no new channel-specific code.\n\n"
    "TRAPS FOUND THE HARD WAY / LEFT DELIBERATELY UNFIXED:\n"
    "1. ~21 of the 70 rows are blank-entry duplicates alongside a "
    "correctly-priced row for the same symbol+expiry, source traced to "
    "\"<symbol>\\n<price1> \\u279d <price2> CLEAN HIT\"-style progress-recap "
    "reposts (a decorative arrow variant of the same running-LTP-repost "
    "bug fixed for channels 66/48/40, see their notes) -- e.g. \"SILVER "
    "250000 PE\\n1800 \\u279d 2600 CLEAN HIT\". A generic whole-message "
    "suppression for this \"<symbol>\\n<num> TO/\\u279d <num> ...\" shape was "
    "tried and REJECTED: across the full 82-channel corpus it also matches "
    "genuine PROFIT-BOOKING messages in already-specialized channels, most "
    "notably Options Train (30, \"PYATM 1700 CE\\n\\n38 TO 57.40\\n\\n14,065"
    "+++++ PROFIT\", 10 occurrences) whose realized-profit total (₹53,425 "
    "baseline) this repo explicitly flags as sensitive to get wrong -- not "
    "safely distinguishable from a real profit recap by shape alone. Left "
    "as a documented residual rather than risk that channel.\n"
    "2. One further symbol-parsing gap, NOT the font issue: \"BUY SILVER "
    "310000 call\" (spelled-out lowercase \"call\", no space-separated CE/PE "
    "token) falls through to an unrelated cash-order fallback and mints a "
    "bare \"SILVER\" trade with the strike number misread as the entry "
    "price (mid 27526). Single occurrence found by sampling; not chased "
    "further given the cost/benefit at this pass.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch7 "
    "· see git log for commit sha"
)


def set_styles(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    Channel.objects.filter(id=29).update(style='auto', style_notes=NRJ_FINANCE)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('traderacker', '0023_batch7_style_notes'),
    ]

    operations = [
        migrations.RunPython(set_styles, noop),
    ]
