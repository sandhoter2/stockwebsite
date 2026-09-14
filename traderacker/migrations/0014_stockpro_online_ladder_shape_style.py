# Updates Channel.style_notes for "Stockpro Online" to reflect the FULL
# 2000-message tracked history (vs. the 51-message sample the earlier
# 0009_stockpro_online_style.py migration was based on). That earlier pass
# only found the "fresh breakout above" / "we shared the research" shapes
# (~13 trades); the full corpus revealed those are a minority slice of a
# much larger DOMINANT shape — 279 of 2000 messages / 275 distinct
# symbol+entry+day calls — that traderacker/signals.py's
# _stockpro_ladder_signal() now also parses. style stays 'mixed' (already
# correct, unchanged). Data-only migration — safely no-ops if the channel
# doesn't exist yet, and is idempotent.
from django.db import migrations

STYLE_NOTES = (
    "Retail tip channel mixing real cash-equity breakout calls with heavy "
    "promo (Master Trader Course / Premium Club ads), FII/DII open-interest "
    "data dumps, and the occasional third-party news link.\n\n"
    "DOMINANT SHAPE (279 of 2000 tracked messages / 275 distinct "
    "symbol+entry+day calls — confirmed by parsing the full pulled "
    "history, not just a sample): a multi-line \"POSITIONAL/SCALPING ... "
    "TRADE|RESEARCH\" header, then the symbol alone on its own line, then "
    "\"Looks Good ABOVE <entry ladder>\" (case varies message to message), "
    "then \"SL <stop>\" (sometimes \"SL or Accumulation Zone <stop>\"), "
    "then \"Targets <ladder>\" — absolute prices in ~56% of rows, \"<ladder> "
    "points from entry\" offsets in ~44% (added to entry, never compared "
    "to it as an absolute level) — then \"Hold <duration>\". Ladder rungs "
    "are separated by '-', '&', '+' or ';' in the corpus. Only the FIRST "
    "rung of each ladder is kept as entry/target, matching this codebase's "
    "existing single-value convention (e.g. RE_TARGET already takes only "
    "the first number of a \"TARGETS 640-650-660\" ladder elsewhere). "
    "Parsed by _stockpro_ladder_signal() in signals.py, style-gated to "
    "'mixed' so no other channel's text can reach it.\n\n"
    "SYMBOL EXTRACTION: unlike the narrower fresh-breakout/shared-research "
    "shapes below (where only the FIRST word of a multi-word name is "
    "trusted, since trailing words are ordinary sentence prose), this "
    "shape's symbol sits ALONE on its own dedicated line, so the FULL line "
    "is concatenated into one token, e.g. \"DATA PATTERN\" -> "
    "\"DATAPATTERN\", \"ANANT RAJ\" -> \"ANANTRAJ\". Truncating to the "
    "first word only (as the narrower shapes do) would collide with this "
    "channel's own macro-commentary prose — \"DATA PATTERN\" truncated to "
    "\"DATA\" collides with \"Data positive/negative...\" daily-outlook "
    "posts, corrupting that trade's peak_profit via parse_signals.py's "
    "substring-word profit-attribution fallback (RE_PIPS's \"<N>pts\" "
    "matching stray \"DOW FUTs <N>pts down\" macro figures as if they were "
    "a booked profit on the open DATA trade). A trailing \"(SHORTALIAS)\" "
    "gives the channel's own short ticker instead, e.g. \"PN GADGIL "
    "(PNGJL)\" -> \"PNGJL\", \"SML MAHINDRA (SMLMAH)\" -> \"SMLMAH\" "
    "(verified against every such row in the full history).\n\n"
    "KNOWN DATA-QUALITY QUIRK IN THE CHANNEL'S OWN TEXT (left as-posted, "
    "not silently fixed): mid 133688 reads \"Looks Good ABOVE 2089-291\" — "
    "almost certainly a typo for \"2910\". The parser takes the literal "
    "FIRST number stated (2089), consistent with how every other entry "
    "regex in this file reads a range/ladder, rather than guessing the "
    "intended value.\n\n"
    "EXPLICIT CLOSES: still exceptionally rare. Across the full 2000-"
    "message history only a handful of messages use \"SL hit\" or "
    "\"crossed all targets\" wording, and almost none of those name BOTH "
    "a symbol and a price in the same message (e.g. \"IFCI crossed all "
    "Targets\" / \"SL hit please exit\" name no price or no symbol) — per "
    "the no-fabrication product rule, those are deliberately left Open "
    "rather than guessing an exit price or attributing an anonymous exit "
    "to whichever trade happened to be open most recently. Only the rare "
    "\"<SYMBOL> crossed all targets, currently at <PRICE>\" phrasing "
    "(which does name both) is handled, via RE_STOCKPRO_CROSSED_TARGETS "
    "in parse_exit_price(). \"MADE A HIGH OF\" / \"LOCKED IN UPPER "
    "CIRCUIT\" follow-ups remain pure price-tracking, never a close (see "
    "the 0009 migration's notes below, still accurate).\n\n"
    "--- Original 0009_stockpro_online_style notes (fresh-breakout / "
    "shared-research shapes, still valid, now a minority slice of this "
    "channel's real signal volume) ---\n\n"
)


def set_style(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    chan = Channel.objects.filter(name='Stockpro Online').first()
    if not chan:
        return
    prior = chan.style_notes or ''
    chan.style = 'mixed'
    chan.style_notes = STYLE_NOTES + prior
    chan.save(update_fields=['style', 'style_notes'])


def unset_style(apps, schema_editor):
    # Revert to the prior (0009) notes by stripping this migration's
    # prepended section back off, rather than blanking style_notes
    # entirely (that would also undo the 0009 migration's own notes).
    Channel = apps.get_model('traderacker', 'Channel')
    chan = Channel.objects.filter(name='Stockpro Online').first()
    if not chan or not chan.style_notes:
        return
    marker = '--- Original 0009_stockpro_online_style notes'
    idx = chan.style_notes.find(marker)
    if idx == -1:
        return
    tail_idx = chan.style_notes.find('---\n\n', idx)
    if tail_idx == -1:
        return
    chan.style_notes = chan.style_notes[tail_idx + len('---\n\n'):]
    chan.save(update_fields=['style_notes'])


class Migration(migrations.Migration):

    dependencies = [
        ('traderacker', '0013_merge_20260914_0932'),
    ]

    operations = [
        migrations.RunPython(set_style, unset_style),
    ]
