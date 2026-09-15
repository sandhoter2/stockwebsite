# Sets Channel.style / style_notes for ProfitPunch (channel 35), the
# third slice of the batch7 8-channel assignment (docs/AGENT_HANDOFF.md
# pattern). Data-only migration -- safely no-ops if the channel doesn't
# exist yet (fresh/test DB), and is idempotent (re-running it just
# overwrites with the same value).
from django.db import migrations

PROFITPUNCH = (
    "ProfitPunch ™ NISM Certified (channel 35) -- a personality-led swing "
    "channel: mostly news links, market commentary, and Hinglish banter, "
    "with an occasional genuine one-shot entry->target call sitting in "
    "single, terse lines. Same house style as Momentum Trades (channel "
    "22) -- shares _momentum_word_to_word_signal -- but spells the "
    "separator uppercase (\"TO\" not \"to\") and sometimes trails the "
    "ticker with emoji before the line break. style='cash'.\n\n"
    "DOMINANT SHAPE: \"BEL \U0001F44C\U0001F44C\\n\\n242 TO 275\", \"TRENT\\n\\n1182 TO "
    "1345\", \"SKF\\n3485 to 3530\", \"CHAMBAL...480 TO 494\" -- single-word "
    "symbol, either directly against the number or alone on its own line "
    "followed by the price pair.\n\n"
    "CHANNEL-AGNOSTIC FIX THIS PASS: RE_MOMENTUM_SAMELINE/_NEXTLINE were "
    "case-sensitive on the literal \"to\" and the next-line variant "
    "required the ticker line to end in only whitespace before the break "
    "-- neither matched this channel's uppercase \"TO\" or emoji-trailed "
    "ticker lines, so it looked parser-blind (0 trades from 934 messages) "
    "despite having the same underlying shape as an already-working "
    "channel. Made both regexes IGNORECASE and added tolerance for up to "
    "10 chars of trailing non-digit junk after the ticker word. "
    "Re-verified empirically safe across every 'cash'-style channel's full "
    "history: this surfaced two new false positives in already-specialized "
    "channels -- Equity99's \"Special 7 To 15\" (a header fragment, not a "
    "ticker) and Swing Trader Vishal's \"Moved 838 To 895\" (stop-loss-"
    "adjustment commentary) -- both added to MOMENTUM_DENY; every other "
    "'cash' channel's Trade count is unchanged or gains only genuine "
    "matches (Momentum Trades +1, Mystocks.in +1, Swing Trader Vishal +4, "
    "spot-checked against source text) after a full unscoped clear+reparse "
    "with the full 169-test suite still green.\n\n"
    "LEFT DELIBERATELY UNFIXED: the bulk of this channel's recent history "
    "(2026) is a different, terser running-commentary shape -- a bare "
    "price alone on its own line, sometimes followed by \"booked ?\"/"
    "\"holding ?\" prompts (\"131\\n\\nbooked ? \U0001F44D\U0001F3FD (holding) tsl should be "
    "110\") -- with no symbol restated per message (the symbol is implied "
    "by channel context/a much earlier message), which this codebase has "
    "no mechanism to resolve and was not attempted here.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch7 "
    "· see git log for commit sha"
)


def set_styles(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    Channel.objects.filter(id=35).update(style='cash', style_notes=PROFITPUNCH)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('traderacker', '0024_batch7_nrj_finance_style'),
    ]

    operations = [
        migrations.RunPython(set_styles, noop),
    ]
