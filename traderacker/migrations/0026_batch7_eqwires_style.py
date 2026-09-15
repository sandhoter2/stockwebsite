# Sets Channel.style / style_notes for Eqwires Research Analyst (channel
# 79), the fourth slice of the batch7 8-channel assignment
# (docs/AGENT_HANDOFF.md pattern). Data-only migration -- safely no-ops if
# the channel doesn't exist yet (fresh/test DB), and is idempotent
# (re-running it just overwrites with the same value).
from django.db import migrations

EQWIRES = (
    "Eqwires Research Analyst(SEBI Registered) (channel 79) -- posts every "
    "trade as a structured, already-completed recap template rather than a "
    "live entry signal: \"Today's High-Quality Trade Update\" header, a "
    "\"Trade Details\" block with Trade type (INTRADAY/BTST), a \"Stock:\" "
    "symbol line, \"Buy Price: ₹<n>\", \"Sell Price: ₹<n>\", and "
    "\"Profit Booked: ₹<n>/-\". style='auto' (the existing generic RE_OPT "
    "path already extracted the right symbol from most \"Stock:\" lines; "
    "the fix needed was purely about recognizing the price/profit "
    "keywords, so no style gate needed).\n\n"
    "DOMINANT SHAPE example:\n"
    "  Trade:  INTRADAY\n  Stock:  PERSISTENT 30 JAN 6200 CE\n"
    "  Buy Price:  ₹167.85\n  Sell Price:  ₹227.85\n"
    "  Profit Booked:  ₹6000/-\n\n"
    "CHANNEL-AGNOSTIC BUGS FIXED THIS PASS (two):\n"
    "1. No regex recognized \"Buy Price:\" as an entry trigger -- every "
    "single one of this channel's 70 pre-existing Trade rows (from "
    "whatever generic path extracted the \"Stock:\" symbol) had entry=None. "
    "Added RE_EQWIRES_BUY_PRICE (\"Buy Price:\\s*₹?\\s*<num>\"), verified "
    "unique to this channel across the full 82-channel corpus (681 "
    "occurrences), used as a message-level entry-fill fallback alongside "
    "this file's other entry-still-None fallbacks. Also added "
    "_eqwires_trade_update_signal, a whole-signal fallback gated on the "
    "\"Trade Details\" anchor phrase (also corpus-unique) for the many "
    "messages the pre-existing generic path did NOT already turn into a "
    "signal at all -- reuses _normalize_close_symbol (already built for "
    "Nirmal Bang Official's close-out path) to strip an expiry-date infix "
    "(\"30 JAN\"), tolerate a missing space before CE/PE (\"6200CE\"), and "
    "reduce a \"<ROOT> <EXPIRY> FUT\" futures line to its bare root (\"MCX "
    "SEP FUT\" -> \"MCX\"). Net effect: 70 -> 681 Trade rows, all newly "
    "correctly entry-priced, 666 of them auto-closing via the existing "
    "profit-booking mechanism below (this channel's messages state their "
    "own outcome).\n"
    "2. parse_profit's thousands-suffix (\"K\") detection was a blanket "
    "`'K' in matched_text.upper()` check -- extending RE_PROFIT_PRE to "
    "also match the word \"Booked\" (needed for \"Profit Booked: ₹6000/-\" "
    "above) meant the word itself (which contains a \"K\") started "
    "tripping that check, inflating every realized profit 1000x (₹6,000 "
    "-> ₹6,000,000). Fixed by requiring the \"K\" sit immediately against "
    "the digits (\"2,175K\"/\"2,175+K\"), the only shape either profit regex "
    "was ever meant to catch. Caught by cross-checking parsed realized "
    "values against source text before trusting the new coverage --\n"
    "  NEVER trust a large coverage jump without spot-checking the actual\n"
    "  numbers, not just that a Trade row now exists.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch7 "
    "· see git log for commit sha"
)


def set_styles(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    Channel.objects.filter(id=79).update(style='auto', style_notes=EQWIRES)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('traderacker', '0025_batch7_profitpunch_style'),
    ]

    operations = [
        migrations.RunPython(set_styles, noop),
    ]
