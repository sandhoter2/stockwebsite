# Sets Channel.style / style_notes for "Options Train ( SEBI REGISTERED)🚆"
# so parse_signals picks the right parsing branch and future maintainers
# understand this channel's exact message format at a glance. Data-only
# migration -- safely no-ops if the channel doesn't exist yet (fresh/test
# DB), and is idempotent (re-running it just overwrites with the same
# values).
from django.db import migrations

CHANNEL_NAME = 'Options Train ( SEBI REGISTERED)\U0001F686'

STYLE_NOTES = (
    "Retail options-tip channel, options-only (no cash/crypto/commodity "
    "calls seen in the tracked history). Every trade follows the same "
    "three-message shape:\n\n"
    "1. ENTRY: a single bare line \"<SYMBOL> <STRIKE> <CE|PE> @ <PREMIUM>\", "
    "e.g. \"NIFTY 23900 PE @ 75\", \"PAYTM 1700 CE @ 38\" -- parsed fine by "
    "the shared RE_OPT regex.\n"
    "2. RUNNING UPDATES: the *same* entry line is reposted verbatim, "
    "followed by the current premium, a rupee PROFIT figure, and either "
    "\"SAFE CAN BOOK\" or \"SAFE BOOK HERE\" -- repeated on almost every "
    "update, not just the final one, e.g. \"PAYTM 1700 CE @ 38\\n41++ \\n\\n"
    "2,175++ PROFIT\\n\\nSAFE CAN BOOK\" then later \"...44++...4,350++ "
    "PROFIT...SAFE CAN BOOK\" then \"...50++...8,700+ PROFIT...SAFE BOOK "
    "HERE\". Only \"SAFE BOOK HERE\" matches the shared RE_EXIT (channel-"
    "agnostic) and closes the trade at the FIRST message where it appears "
    "-- by design (parse_signals never reopens a Closed trade), so the "
    "realized profit locked in is whichever booking figure happened to "
    "carry that exact phrase, not necessarily this channel's best/final "
    "number. \"SAFE CAN BOOK\" does NOT match RE_EXIT (verified: that exact "
    "phrase is unique to this channel among all 76 tracked, so leaving it "
    "unmatched cannot affect any other channel) and so those trades close "
    "only via the existing 30%-trailing-drawdown safety net once profit "
    "later dips, or via the end-of-day recap below when one is posted -- "
    "left as-is rather than added to RE_EXIT, since doing so was verified "
    "empirically to make realized profit *more* understated for this "
    "channel (it would lock in the very first, usually smallest, booking "
    "figure instead of letting the trailing stop or the recap capture a "
    "later, larger one).\n"
    "3. END-OF-DAY / PREMIUM-CALL RECAP (sometimes the *only* message ever "
    "posted for a trade, with no separate entry line): \"<SYMBOL> <STRIKE> "
    "<CE|PE>\\n\\n<ENTRY> TO <EXIT>\\n\\n<PROFIT>+++ PROFIT\\n\\nROI <N>%\", "
    "e.g. \"BSE 3500 CE\\n\\n85 TO 114\\n\\n5,800+++++ PROFIT\\n\\nROI 34%\". "
    "Added RE_TO_RANGE_OPT + a parse_exit() branch for this shape (an "
    "explicit \"<entry> TO <exit>\" pair immediately after the option leg, "
    "with the literal word PROFIT within ~80 chars after it) so these "
    "recaps now correctly close the trade at its true final profit instead "
    "of being left Open forever with only peak_profit set. Verified this "
    "shape's \"PROFIT\" requirement is unique to this channel: 4 other "
    "channels post superficially similar \"<price> TO <price>\" option "
    "recaps (channels 41, 42, 66, 68, 72) but phrase their close-out as "
    "\"...POINT DONE...% ROI DONE\" (no literal PROFIT word nearby), so "
    "they are untouched by this addition.\n\n"
    "OTHER FORMAT NOTES:\n"
    "  - A one-line \"Premium Call\" recap with NO \"TO\" range and no \"@\" "
    "premium, e.g. \"IDEA 15 CE\\n\\n3500++ Profit\", used to be misparsed: "
    "the shared option regex greedily grabbed the *profit* figure across "
    "the blank line as if it were the entry premium (entry=3500 instead of "
    "unknown). Fixed by not treating a number as an entry price when there "
    "was no \"@\"/\":\" price marker AND the number is immediately followed "
    "by \"++\"/\"PROFIT\" -- narrowly scoped (checked against the other 75 "
    "channels' full history: no legitimate cross-newline entry price is "
    "ever immediately followed by \"++\"/PROFIT, so nothing else changes). "
    "Left as Open with entry=None -- there's no confident entry price and "
    "no exit phrase either, so no trade lifecycle can be inferred.\n"
    "  - Symbol typos are NOT normalized: \"PYATM 1700 CE\" (typo for "
    "PAYTM) is a same-day recap of the earlier \"PAYTM 1700 CE @ 38\" "
    "position under a misspelled ticker; it becomes its own separate Trade "
    "row rather than being merged into the original.\n"
    "  - Occasional mixed-case symbols in \"Premium Call\" posts (e.g. "
    "\"Paytm 1720 CE\" for what looks like a *different* strike than the "
    "day's main \"PAYTM 1700 CE\" call) are deliberately left unparsed -- "
    "this codebase's ALL-CAPS ticker convention is what keeps prose words "
    "from becoming phantom trades, and loosening it for one channel isn't "
    "worth that risk for a single one-off post.\n"
    "  - \"NEW LOCK CALL\" posts (external cosmofeed.com paid-tip links) "
    "and the \"OptionsTrainElite\"/\"PREMIUM STOCK MARKET CHANNEL\" "
    "membership pitches are correctly caught by is_promo() (no BUY/SELL/"
    "CE/PE trade verb) and produce no trade rows."
)


def set_style(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    Channel.objects.filter(name=CHANNEL_NAME).update(
        style='options', style_notes=STYLE_NOTES)


def unset_style(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    Channel.objects.filter(name=CHANNEL_NAME).update(
        style='auto', style_notes='')


class Migration(migrations.Migration):

    dependencies = [
        ('traderacker', '0008_motilal_oswal_official_style'),
    ]

    operations = [
        migrations.RunPython(set_style, unset_style),
    ]
