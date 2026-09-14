# Sets Channel.style / style_notes for "Motilal Oswal - Official📈💸" (the
# official Motilal Oswal broker research desk channel) so parse_signals picks
# the right parsing branch and future maintainers understand this channel's
# exact message format at a glance. Data-only migration — safely no-ops if
# the channel doesn't exist yet (fresh/test DB), and is idempotent
# (re-running it just overwrites with the same values).
from django.db import migrations

STYLE_NOTES = (
    "Official Motilal Oswal broker research desk. Clean, consistent, "
    "template-generated cash-equity BUY tips — no options/crypto/futures "
    "seen in the tracked history (2026-09-01 onward). Two interchangeable "
    "tip headers, identical body shape:\n\n"
    "1. \"MOSt Overnight\" (short-term/overnight idea) and \"Conviction "
    "Delivery Idea\" (swing/delivery idea):\n"
    "\"MOSt Overnight  \\n\\nBUY SGMART  \\n\\nCMP 852.05 \\nSL 826 \\n"
    "TGT 906.4 \\n\\n- <one-line technical rationale>\\n\\n"
    "Disclaimer - https://ftp.motilaloswal.com/emailer/Marketdiary/"
    "Disclaimer/Disclaimer.pdf\". CMP is the entry, SL/TGT are always "
    "absolute rupee prices. Already parsed correctly by the generic "
    "verb-first regex (RE_VERB_FIRST bridges \"BUY <SYM>\" across the "
    "blank line to \"CMP <price>\" via \\s*) — see "
    "test_verb_first_with_cmp. Always BUY, never SELL, in the tracked "
    "history.\n\n"
    "2. Daily \"📊 3 Things That Will Decide the Market Today\" digest: a "
    "long macro/options-levels post that ends with a \"Fundamental Picks\" "
    "numbered list (\"1.Titan- Target 6000 (19%)\") and a single "
    "\"Technical Pick\" (\"HCL TECHNOLOGIES Ltd BUY\\nPrevious Close: "
    "1351\\nTarget: 1425\\nPotential upside: ~5%\"). DELIBERATELY LEFT "
    "UNPARSED: company names here are multi-word/mixed-case (\"Sai Life "
    "Sciences Ltd\", \"Urban Company\") rather than the ALL-CAPS NSE "
    "ticker convention (\"SAILIFE\") this codebase relies on for symbol "
    "detection, there is no ticker lookup table to translate one to the "
    "other, and there's no stop-loss (only an entry-adjacent BUY with no "
    "number directly after it, which already fails RE_BUYSELL/"
    "RE_VERB_FIRST's price requirement — confirmed empirically these "
    "never produce a phantom signal). Guessing a ticker from the company "
    "name would risk a wrong/unverifiable trade row, which the parser's "
    "\"no confident match -> no trade\" philosophy rules out.\n\n"
    "NOISE (no signal, verified never fires a false positive): promo "
    "\"Join Now : https://www.motilaloswal.com/campaign/...\" links, "
    "caught by is_promo() as a bare no-trade-verb link, plus the periodic "
    "webinar/StratX registration posts (caught via the 'registration'/"
    "'webinar' keywords), and recurring educational engagement posts "
    "(\"💥 Bazaar Busters!\", \"🕯 Candle pe "
    "Charcha\", \"🎯 Chart Attacks\", quiz polls) that sometimes contain "
    "prose words like \"exit\" (e.g. \"...trapped sellers were waiting "
    "for a bounce to exit\") which trip the channel-agnostic RE_EXIT "
    "keyword match — harmless here because parse_signals only acts on an "
    "exit when a rupee profit figure is ALSO present (book() no-ops when "
    "profit is None), and none of these posts ever pair \"exit\" with a "
    "profit figure.\n\n"
    "EXITS: no explicit close-out message (\"SOLD\", \"BOOKED\", \"EXIT "
    "<SYM> @ <PRICE>\") has been observed from this channel in the "
    "tracked history — this broker desk appears to post entries only and "
    "not follow up with booking updates in this Telegram feed, so open "
    "positions here rely on the trailing-drawdown auto-close in "
    "parse_signals rather than an explicit exit phrase."
)


def set_style(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    Channel.objects.filter(name='Motilal Oswal - Official📈💸').update(
        style='cash', style_notes=STYLE_NOTES)


def unset_style(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    Channel.objects.filter(name='Motilal Oswal - Official📈💸').update(
        style='auto', style_notes='')


class Migration(migrations.Migration):

    dependencies = [
        ('traderacker', '0007_angel_one_research_style'),
    ]

    operations = [
        migrations.RunPython(set_style, unset_style),
    ]
