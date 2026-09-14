# Sets Channel.style / style_notes for "Angel One Research" (the official
# Angel One broker research desk channel) so parse_signals picks the right
# parsing branch and future maintainers understand this channel's exact
# message format at a glance. Data-only migration — safely no-ops if the
# channel doesn't exist yet (fresh/test DB), and is idempotent (re-running
# it just overwrites with the same values).
from django.db import migrations

STYLE_NOTES = (
    "Official Angel One broker desk. Very clean, consistent, machine-"
    "generated formatting (no emoji spam / astrology / regional languages "
    "seen on retail tip channels) — two message shapes only:\n\n"
    "1. CASH EQUITY ENTRY: \"\U0001F7E2 BUY <SYMBOL> <N> shares at <PRICE>.\\n\\n"
    "Message : SL <SL> TGT <TGT> Modify Qty/ Lot as per your discretion\\n\\n"
    "Created Date & Time\\n<time>\\n<date>\\n\\nDisclaimer : "
    "www.angelone.in/research-disclaimer - Angel One Ltd\". SL/TGT are "
    "always absolute rupee prices, never percentages.\n\n"
    "2. OPTIONS ENTRY (broker order ticket style, with an explicit expiry "
    "date between the index and the strike): \"\U0001F7E2 BUY NIFTY 03 JUL 25 "
    "25700 CE 1 lots at 109.00.\\n\\nExpiry : 03-Jul-2025\\n\\nMessage : SL 94 "
    "TGT 135 ...\". \U0001F534 (red circle) prefixes SELL/PE-side orders instead "
    "of \U0001F7E2. This format ONLY appears in this channel among the 76 "
    "tracked (verified empirically) — it needs RE_OPT_EXPIRY, not the plain "
    "RE_OPT premium regex.\n\n"
    "EXITS/PROFIT BOOKING — several interchangeable phrasings, all "
    "give an absolute exit price rather than a rupee profit total:\n"
    "  - \"EXIT [FROM] <SYMBOL>[ ]@<PRICE>\" e.g. \"EXIT RTNINDIA @ 63.3\", "
    "\"EXIT FROM MRPL@144.2\"\n"
    "  - \"BOOK PROFIT IN <SYMBOL> @<PRICE>\" / \"BOOK PROFIT IN "
    "<SYMBOL>@<PRICE>\" e.g. \"BOOK PROFIT IN GMDCLTD @422.5\" — handled by "
    "the channel-agnostic RE_EXIT_PRICE_BOOK added for this format (no "
    "other channel used this phrasing as of the 2026-09 audit)\n"
    "  - Bare \"BOOK @ <PRICE>\" / \"BOOK PROFIT @<PRICE>\" (no symbol — "
    "applies to whichever trade the message is a reply/follow-up to; the "
    "parser has no way to resolve these against a specific position)\n"
    "  - Occasionally the option strike stands in for a symbol, e.g. "
    "\"BOOK PROFIT IN 57000 PE @ 583.5\" — deliberately left unparsed "
    "(no confident symbol) rather than guessed\n"
    "  - Options can also close via \"SL HIT @ <PRICE>\" or "
    "\"EXIT POSITIONS @<PRICE>\" on a reply to the original order message\n"
    "  - Symbol typos happen and are NOT normalized, e.g. "
    "\"BOOK PROFIT IN POONAWALA @ 461\" vs. the entry's \"POONAWALLA\" — "
    "that trade is left Open rather than fuzzy-matched\n\n"
    "COMPLIANCE NOTICE (2025-07-04 onward): after a SEBI compliance change "
    "this channel stopped posting recommendations and now only reposts a "
    "recurring promo (\"\U0001F680 Don't miss our latest research "
    "recommendations... Join here...\") pointing users to a private, "
    "registered-users-only channel. These are correctly caught by is_promo() "
    "(no BUY/SELL/CE/PE trade verb) and produce no trade rows. No live "
    "signals have posted here since then — style covers the earlier active "
    "period."
)


def set_style(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    Channel.objects.filter(name='Angel One Research').update(
        style='mixed', style_notes=STYLE_NOTES)


def unset_style(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    Channel.objects.filter(name='Angel One Research').update(
        style='auto', style_notes='')


class Migration(migrations.Migration):

    dependencies = [
        ('traderacker', '0006_quote_asof_datetime'),
    ]

    operations = [
        migrations.RunPython(set_style, unset_style),
    ]
