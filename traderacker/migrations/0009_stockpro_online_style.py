# Sets Channel.style / style_notes for "Stockpro Online" so parse_signals
# picks the right parsing branch and future maintainers understand this
# channel's exact message format at a glance. Data-only migration — safely
# no-ops if the channel doesn't exist yet (fresh/test DB), and is idempotent
# (re-running it just overwrites with the same values).
from django.db import migrations

STYLE_NOTES = (
    "Retail tip channel mixing real cash-equity breakout calls with heavy "
    "promo (Master Trader Course / Premium Club ads), FII/DII open-interest "
    "data dumps, and the occasional third-party news link. Two distinct "
    "phrasings carry a real entry level, BOTH in lower/mixed case rather "
    "than this codebase's usual ALL-CAPS \"ABOVE\"/\"BELOW\"/\"BREAKOUT\" "
    "convention, so the channel-agnostic RE_CASH (case-sensitive on "
    "purpose, to avoid matching ordinary prose like \"...it looks good "
    "above 237\" in other channels) never fired for this one. Added two "
    "scoped-case-insensitive regexes (RE_FRESH_BREAKOUT, "
    "RE_SHARED_RESEARCH) that keep the leading symbol ALL-CAPS-only (same "
    "false-positive protection as RE_CASH) and only relax case on the "
    "fixed keyword phrase itself:\n\n"
    "1. Standalone breakout call: \"LUMINO fresh breakout above 112\", "
    "\"APOLLO MICRO fresh breakout above 418\". Only the FIRST word "
    "becomes the trade symbol (\"APOLLO\"), matching this codebase's "
    "single-token shorthand-ticker convention elsewhere.\n\n"
    "2. \"We shared the research\" recap / social-proof post that "
    "retrospectively documents an earlier call's entry level and is the "
    "ONLY record of that call in the tracked history (no matching "
    "standalone breakout message exists for it), e.g. \"✅MILKYMIST 🔥 - "
    "We shared the research 2nd September 2026 only that it looks good "
    "above 237\\n\\nToday it made a high of 292.75...\" or \"✅DHOOTTRANS "
    "🔥 - In morning we shared the research that it looks good above "
    "1620\". Also first-word-only, e.g. \"VA\" from \"VA TECH WABAG\".\n\n"
    "KNOWN QUIRK (left as-is, not worth a hardcoded alias map): the "
    "channel is internally inconsistent about which shorthand it uses for "
    "the same stock — \"DHOOT fresh breakout above 1620\" vs. \"DHOOTTRANS "
    "🔥 - ... it looks good above 1620\" (same level, same day) produce "
    "two separate Trade rows (DHOOT, DHOOTTRANS) rather than one, since "
    "the upsert key is (channel, trade, entry). Harmless duplication, not "
    "a wrong price.\n\n"
    "NOT SIGNALS (verified never fires a false positive): \"<SYM> MADE A "
    "HIGH OF <price>\" follow-ups (e.g. \"✅RAYMOND MADE A HIGH OF "
    "974.85🚀🚀\") are pure price-tracking updates on an already-open call, "
    "not new orders or exits — no BUY/SELL/breakout keyword, so no new "
    "signal, and no SAFE BOOK/BOOKED/EXIT/SL HIT wording either, so "
    "RE_EXIT never fires and the trade correctly stays Open (product "
    "rule: a trade only closes on an explicit close-out phrase, never "
    "because a later quote crossed the target). NIFTY/BANKNIFTY strike-"
    "wise long/short OI dumps (\"23200 -\\nLongs - 3.10L (Intraday - "
    "1.95L)...\") contain no ALL-CAPS ticker/price pair the regexes "
    "recognize as a signal. Course-admission and free-webinar promo posts "
    "and third-party news links (e.g. a Volkswagen-JSW joint-venture "
    "article) also correctly produce no signal.\n\n"
    "EXITS: no explicit close-out message (SOLD/BOOKED/EXIT/SL HIT) has "
    "been observed from this channel in the tracked history — every "
    "resulting Trade row stays Open, which is the correct/conservative "
    "outcome per the no-auto-close product rule, not a parser bug."
)


def set_style(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    Channel.objects.filter(name='Stockpro Online').update(
        style='mixed', style_notes=STYLE_NOTES)


def unset_style(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    Channel.objects.filter(name='Stockpro Online').update(
        style='auto', style_notes='')


class Migration(migrations.Migration):

    dependencies = [
        ('traderacker', '0008_motilal_oswal_official_style'),
    ]

    operations = [
        migrations.RunPython(set_style, unset_style),
    ]
