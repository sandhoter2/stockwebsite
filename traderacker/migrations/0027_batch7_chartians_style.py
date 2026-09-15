# Sets Channel.style / style_notes for THE CHARTIANS (channel 72), the
# fifth slice of the batch7 8-channel assignment
# (docs/AGENT_HANDOFF.md pattern). Data-only migration -- safely no-ops if
# the channel doesn't exist yet (fresh/test DB), and is idempotent
# (re-running it just overwrites with the same value).
from django.db import migrations

CHARTIANS = (
    "THE CHARTIANS (channel 72) -- an index-options tipster (SENSEX CE/PE, "
    "occasionally BANKNIFTY/NIFTY), plus unrelated market-commentary/"
    "education/promo prose the generic parser correctly ignores. Was "
    "misclassified style='auto'; corrected to style='options' this pass.\n\n"
    "DOMINANT SHAPE: \"SENSEX 77300 CE\\n\\nEXPIRY 03 SEPTEMBER\\n\\nAbove - "
    "500\\n\\nTG - 550 / 600 / 650 / 700\\n\\nSL - PAID\\n\\nWait for "
    "level\" -- a strike header with an \"EXPIRY <day> <month>\" infix "
    "before the entry trigger, same shape family as Stock Gainers/ROCHIT "
    "SINGH STOCKS' dated headers (see their notes), which only the "
    "style=='options' date-infix fallback block in parse_message reaches. "
    "Under the (wrong) style='auto' this channel had been set to, "
    "15 of its 56 pre-existing Trade rows had entry=None; switching the "
    "style alone (no new regex needed) fixed 13 of them, taking the "
    "channel to 48 Trade rows with only 2 residual blank-entry ones "
    "(source: no-digit commentary follow-ups like \"SENSEX 78700 CE\\n"
    "Buy\"/\"SENSEX 79100 PE\\nJackpot Entry\" -- deliberately NOT "
    "suppressed as reposts, since the same bare-shape pattern is also how "
    "several other channels state a GENUINE fresh entry, e.g. channel 17's "
    "\"CRUDEOIL 9700 CE\\nDay high break out\"; not safely distinguishable "
    "by shape alone, same conclusion reached for ROCHIT SINGH STOCKS/40's "
    "equivalent residual -- see its notes).\n\n"
    "Verified via a full unscoped clear+reparse that switching this "
    "channel's style produced no unexpected side effects elsewhere (only "
    "this channel's own Trade rows changed) and the full 174-test suite "
    "stayed green.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch7 "
    "· see git log for commit sha"
)


def set_styles(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    Channel.objects.filter(id=72).update(style='options', style_notes=CHARTIANS)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('traderacker', '0026_batch7_eqwires_style'),
    ]

    operations = [
        migrations.RunPython(set_styles, noop),
    ]
