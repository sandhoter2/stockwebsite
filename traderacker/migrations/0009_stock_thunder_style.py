# Sets Channel.style / style_notes for "Stock Thunder" so parse_signals picks
# the right parsing branch and future maintainers understand this channel's
# exact message format at a glance. Data-only migration — safely no-ops if
# the channel doesn't exist yet (fresh/test DB), and is idempotent
# (re-running it just overwrites with the same values).
from django.db import migrations

STYLE_NOTES = (
    "Index/stock OPTION tips only (NIFTY, SENSEX, and a handful of single "
    "-stock options like BIOCON/EICHERMOT/IOC) — no plain cash-equity, "
    "crypto or forex calls seen in the tracked history. Two message "
    "shapes, plus running price-update recaps for each open position:\n\n"
    "1. Entry: \"Buy NIFTY\\xa0 _23650PE Above 190-200\\n\\nTarget : "
    "250/310/360\\n\\nStoploss : Paid\" — note the underscore joining the "
    "index name to the strike+right (\"_23650PE\", no space), and that "
    "\"Above 190-200\" is an entry TRIGGER range, not an entry/target "
    "pair like other channels' \"₹250-320\" shorthand. RE_OPT's root "
    "pattern now tolerates an optional underscore (and any amount of "
    "whitespace, not just 0-1 char) between the letters and the strike "
    "digits so \"NIFTY _23650PE\" parses as one option instead of zero "
    "signals. A new RE_ABOVE_BELOW fallback (checked before the older "
    "bare dash-range fallback) takes the first number after ABOVE/BELOW "
    "as the entry when no premium is given directly after CE/PE — NUM "
    "stops at the first non-digit so \"190-200\" naturally yields entry "
    "190 without a separate range-specific branch. \"Stoploss : Paid\" "
    "never gives a numeric SL (stays None, no crash). Also used for the "
    "single-stock \"POSITIONAL STOCK OPTION TRADE\\n\\nBUY BIOCON 400 CE "
    "ABOVE 10 TRG - 12-14-17 SL PAID\" shape — RE_TARGET now also "
    "recognizes the \"TRG\" abbreviation (previously only VIEW/TARGETS?/"
    "TGT/SHT), giving target=12 (first of the TRG list).\n\n"
    "2. Progress-update recap on an already-open leg, posted repeatedly "
    "through the day with no BUY/SELL verb: \"170 TO 199#NIFTY 23650PE "
    "\\n\\nGAINING RS- 4000/ 2 LOTS \\n\\nFIRST TARGET ALMOST HIT \\n\\n"
    "BOOK PARTIAL PROFIT OR TRAIL SL\". Restating the option leg here "
    "used to create a second, entry=None duplicate Trade row alongside "
    "the correctly-entered original (same channel+trade, different "
    "entry -> different upsert key). A new RE_PROGRESS_UPDATE guard "
    "('<num> TO <num>#') now skips any option match that starts right "
    "after this recap prefix, so these messages correctly produce zero "
    "fresh signals — they only carry a profit update. \"GAINING RS- "
    "<amount>/ <lots> LOTS\" is this channel's own profit phrasing (it "
    "never uses the word \"profit\" the way other channels' PROFIT_POST/"
    "PROFIT_PRE regexes expect); a new RE_GAINING pattern feeds this "
    "into parse_profit() so peak_profit tracking works for this "
    "channel. \"FIRST/SECOND/ALL TARGET ALMOST/FULL HIT ... BOOK "
    "PARTIAL PROFIT OR TRAIL SL\" is deliberately NOT an explicit close "
    "-out (no SOLD/BOOKED/full-EXIT wording, and \"TARGET HIT\" as a "
    "literal phrase never appears — it's always \"TARGET ALMOST/FULL "
    "HIT\", which RE_EXIT does not match) — per product convention "
    "these positions stay Open in the tracked history and rely on the "
    "trailing-drawdown auto-close, never an explicit exit sentence.\n\n"
    "KNOWN GAP: three progress-recap messages use a hashtag that fuses "
    "the \"POSITIONAL\" label straight onto the ticker with no space "
    "(\"#POSITIONAL_IOC 140 PE\", \"#POSITIONAL_EICHERMOT 7800 PE\"). "
    "The underscore keeps \\b word-boundary matching from ever reaching "
    "the ticker, so these three messages correctly produce no new "
    "signal (as before), but parse_signals' fallback profit-attribution "
    "(matching whitespace-split words against open trades by "
    "trade__icontains) also can't find the ticker inside the fused "
    "token \"POSITIONAL_IOC\", so their GAINING RS profit figures don't "
    "get attached to the IOC/EICHERMOT trades. Left unfixed: the "
    "affected trades' entry/direction/target are still correct, only "
    "their displayed peak_profit is a little stale, and a general fix "
    "would mean changing the shared word-tokenization fallback in "
    "parse_signals.py (out of this channel's scope) rather than "
    "signals.py itself.\n\n"
    "'POSITIONAL' was added to STOP_WORDS (this channel's recurring "
    "\"POSITIONAL STOCK OPTION TRADE\" label line was previously being "
    "read as a phantom cash symbol via the generic ABOVE/BELOW regex's "
    "loose word-skipping). Also, option roots claimed by the main "
    "option regex (not just the broker-expiry variant) are now tracked "
    "and excluded from the looser cash/verb-first/buysell regexes, so "
    "e.g. \"BUY BIOCON 400 CE ABOVE 10\" no longer also spawns a phantom "
    "cash \"BIOCON\" trade at entry=400 (the strike, misread as a "
    "price) alongside the real option row. This fix is channel-agnostic "
    "and was verified (full parse_signals run across all 76 channels) "
    "to also remove several pre-existing phantom strike-as-price cash "
    "trades on other channels (e.g. \"NIFTY 23800 CE @75\" no longer "
    "also creates a bogus \"NIFTY\" cash trade at entry=23800) — a net "
    "improvement, not a regression; see the commit message for the "
    "full per-channel before/after accounting.\n\n"
    "Promo/paid-group ads (\"OFFER OFFER OFFER\", \"Join Our Paid "
    "Channel\") are correctly caught by is_promo()."
)


def set_style(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    Channel.objects.filter(name='Stock Thunder').update(
        style='options', style_notes=STYLE_NOTES)


def unset_style(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    Channel.objects.filter(name='Stock Thunder').update(
        style='auto', style_notes='')


class Migration(migrations.Migration):

    dependencies = [
        ('traderacker', '0008_motilal_oswal_official_style'),
    ]

    operations = [
        migrations.RunPython(set_style, unset_style),
    ]
