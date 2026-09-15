# Sets Channel.style / style_notes for Vizu Stock Market Hints (channel
# 2), the sixth and last slice of the batch7 8-channel assignment
# (docs/AGENT_HANDOFF.md pattern). Data-only migration -- safely no-ops if
# the channel doesn't exist yet (fresh/test DB), and is idempotent
# (re-running it just overwrites with the same value).
from django.db import migrations

VIZU = (
    "Vizu Stock Market Hints (channel 2) -- an index-options tipster "
    "(NIFTY/BANKNIFTY/SENSEX CE/PE), house style close to ROCHIT SINGH "
    "STOCKS/Trading With Ca Abhay: hashtag-prefixed strike headers "
    "(\"#SENSEX77300CE\", no space before CE/PE), reposted live as a "
    "decorated progress-recap. style='auto' (tried style='options' during "
    "this pass to see if it would help the way it did for THE CHARTIANS/"
    "72 -- verified empirically it makes NO difference here, same 63 "
    "Trade rows / 22 null-entry either way, so left at 'auto').\n\n"
    "DOMINANT SHAPE (correctly parsed): \"BUY SENSEX 76300 put\\n330\", "
    "\"NIFTY 11 Aug 24500 PE\\n\\nONLY IN RANGE  58 - 62\" -- real entries "
    "already work fine via the existing generic/NEAR-style paths.\n\n"
    "LEFT DELIBERATELY UNFIXED (22 of 63 rows are blank-entry): a "
    "decorated \"#<symbol>\\n\\n<emoji><num> TO <num>+++<emoji> FIRST "
    "TARGET ARCHIVE\" progress-recap of an already-open leg (e.g. "
    "\"#SENSEX77300CE\\n\\n\\U0001F914500 TO 550+++\\u2714\\ufe0f\\u2705\\n\\nFIRST "
    "TARGET ARCHIVE\"). This is the exact same shape/root-cause as the "
    "\"<symbol>\\n<num> TO/\\u279d <num> ...\" progress-arrow repost residual "
    "documented for Nrj finance (29): a generic whole-message suppression "
    "for this shape was tried and REJECTED there because across the full "
    "82-channel corpus it also matches GENUINE profit-booking messages in "
    "Options Train (30, whose realized-profit total this repo explicitly "
    "flags as sensitive to get wrong), so it is not safely distinguishable "
    "by shape alone -- see channel 29's style_notes and migration "
    "0024_batch7_nrj_finance_style for the full investigation. Applying "
    "here for the same reason rather than re-deriving it.\n\n"
    "last agent: 2026-09-15 · /Users/mamathap/Downloads/worktrees/batch7 "
    "· see git log for commit sha"
)


def set_styles(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    Channel.objects.filter(id=2).update(style='auto', style_notes=VIZU)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('traderacker', '0027_batch7_chartians_style'),
    ]

    operations = [
        migrations.RunPython(set_styles, noop),
    ]
