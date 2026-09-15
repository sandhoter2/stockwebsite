# Sets Channel.style / style_notes for the 8 channels covered by the
# "batch1" stakeholder pass (RAJESH PALVIYA, Bloomberg, Easy trading classes,
# Equitymaster, Money creates Money, No Paid Service (@Anirbban public
# channel), PL Technical Research, Priya Yaduvanshiiii). All 8 turned out to
# be non-signal channels in their tracked history: pure news/research wires,
# link-only feeds, hype/engagement spam, or prose-only technical commentary
# with no machine-parseable BUY/SELL/entry-price format. None needed a
# signals.py regex change. Data-only migration — each channel's update is
# independently a no-op (via .filter(name=...)) if that channel is absent,
# and the whole thing is idempotent (re-running just overwrites with the
# same values), matching the established per-channel migration pattern (see
# e.g. 0008_motilal_oswal_official_style.py).
from django.db import migrations

RAJESH_PALVIYA_NOTES = (
    "Emoji hype/engagement channel, not a real signals feed. The bulk of the "
    "tracked history (2026-09-11 to 2026-09-14) is disconnected numeric "
    "\"price ladder\" spam with no symbol ever attached (\"210\\U0001F911\\U0001F911\", "
    "\"205\\U0001F911\\U0001F911\", ...) interspersed with \"TARGET DONE\"/\"MAZA AAYA NA\" "
    "celebration posts, group-plan pricing/CTA spam (\"ZERO HERO TRADE "
    "PREMIUM\", \"JOIN NOW FAST PREMIUM GROUP\"), and Hindi promo prose "
    "urging users to join a paid group — none of it names a tradable "
    "symbol.\n\n"
    "The one message that does name a symbol, \"SENSEX 75200 CE ... FROM "
    "195 TO 388++ ... ALL TARGET DONE IN PREMIUM ... 193++++points\", is "
    "itself an already-closed recap posted after the fact with no separate "
    "entry message anywhere in the tracked history. Before this change, "
    "style='auto' let RE_OPT match the \"SENSEX 75200 CE\" leg but none of "
    "the entry-fill fallbacks (@/ABOVE-BELOW/RANGE) recognized the \"FROM X "
    "TO Y\" phrasing or the \"++++points\"/\"ALL TARGET DONE\" wording (no "
    "\"PROFIT\"/\"TARGET HIT\" keyword), so it upserted a phantom "
    "permanently-Open trade with entry=None, target=None, stop_loss=None "
    "that could never close — a real bug, fixed here purely by "
    "classification (style='promo' short-circuits parse_message entirely) "
    "rather than a fragile single-message regex, since \"FROM <n> TO <n>\" "
    "recap phrasing is also used by several other, differently-formatted "
    "channels outside this batch and a bespoke regex risked collision "
    "there for a single data point."
)

BLOOMBERG_NOTES = (
    "Bloomberg's official news feed — general macro/markets journalism "
    "with article links (bloom.bg/…, podtrac.com/…), never a trade call. "
    "No BUY/SELL/CE/PE/ABOVE/BELOW signal has ever been posted here. "
    "Ordinary prose occasionally contains a RE_EXIT keyword by coincidence "
    "(\"…traders hunkered down at home or booked hotels…\" -> \"booked\"; "
    "\"…AI-enabled teddy bear sold by a Singapore-based company…\" -> "
    "\"sold\"; \"…decision to not continue "
    "beyond February exit exposed deep divisions…\" -> \"exit\"), and "
    "market-move headlines can coincidentally match RE_PIPS (\"…Sensex "
    "Today Tanks 566 Points…\") — harmless today since this channel never "
    "has an Open trade for parse_signals.book()/close_at_price() to act "
    "on, but style='promo' stops signal extraction outright and documents "
    "that this is expected, not a parsing gap."
)

EASY_TRADING_CLASSES_NOTES = (
    "Every tracked message (2026-05-31 to 2026-08-20) is a bare YouTube "
    "link (\"https://youtu.be/...\") with no caption text at all — an "
    "education/vlog channel, not a signals feed. Zero matches of any kind "
    "(signals/profit/exit/exit-price) in the tracked history; nothing to "
    "fix."
)

EQUITYMASTER_NOTES = (
    "Equitymaster's research-newsletter feed: #EMMarkets/#EMViewsOnNews/"
    "#EMProfitHunter/#EMTheLongView digest posts, each a headline + a link "
    "to the full article (eqtm.in/...), plus \"Access Complete Details\" "
    "report-purchase CTAs. No BUY/SELL/entry-price call is ever posted — "
    "these are informational/marketing, not trade signals. The recurring "
    "\"#EMMarkets - Sensex Today Tanks 566 Points | Nifty Below 23,500\" "
    "index-recap headlines coincidentally match RE_PIPS (the word "
    "\"Points\") and get read as a rupee profit figure by parse_profit() — "
    "harmless since this channel never has an Open trade to attach it to, "
    "but real noise if it ever did. style='promo' suppresses new phantom "
    "signal extraction (parse_profit/parse_exit still run channel-agnostic "
    "in parse_signals.py but stay no-ops with no Open trades here)."
)

MONEY_CREATES_MONEY_NOTES = (
    "\"Vibhor Varshney\"'s channel: IPO comparison/review videos (YouTube "
    "links), Hindi/Hinglish market-mood commentary, and informal trade "
    "narration that never follows a machine-parseable shape — e.g. "
    "\"Kingfa\\n\\nEntered at 5400 now at 6250\\n\\n850 points in pocket\" "
    "(past-tense recap, no BUY/ABOVE/CE-PE keyword), \"Hindalco\\n\\n"
    "Blassssted downside\\n\\n960 pe\\n\\n1st target done\" (bare strike+PE "
    "with no CE/PE-adjacent number pattern RE_OPT expects), \"Continental "
    "securities Ltd ... Currently trading at 23 and can head towards 38 - "
    "41 levels\" (a target range with no distinguishable entry trigger). "
    "None of the 50 tracked messages produce a signal today, and none "
    "should: the phrasing is too loose/narrative to add a targeted regex "
    "without risking phantom trades from ordinary stock-commentary prose "
    "elsewhere in the channel (which is most of its content). Several "
    "messages coincidentally match RE_PIPS/RE_PROFIT_POST/RE_GAINING on "
    "plain point/rupee figures embedded in prose (\"850 points in "
    "pocket\", \"Rs 7000 profits per lot\") — harmless no-ops today since "
    "there's never an Open trade in this channel to book them against. "
    "style='promo' documents this and stops speculative signal matching."
)

NO_PAID_SERVICE_NOTES = (
    "\"No Paid Service (@Anirbban public channel)\" — every tracked "
    "message (2026-09-01 to 2026-09-12) is a bare X/Twitter status link "
    "(https://x.com/Anirbban/status/... or .../anirbban/status/...), "
    "occasionally with a one-word caption (\"good chance\"). No symbol, "
    "price, or trade keyword ever appears in the stored text — the actual "
    "call content lives on X, not in this Telegram feed. Zero matches of "
    "any kind in the tracked history; nothing to fix."
)

PL_TECHNICAL_RESEARCH_NOTES = (
    "PL Capital's official research-desk feed: IPO/listing news links "
    "(plindia.com/news/...), \"Top Picks\"/\"Market Snapshot\"/\"Sector "
    "Snapshot\" web-story links, webinar invites, and raw index/FII-DII "
    "data dumps (\"PL TECH: Global Indices\\nGIFT Nifty: 23349 -135...\"). "
    "No BUY/SELL/entry-price call is ever posted in the tracked history — "
    "everything is a headline pointing to an external article, or a data "
    "snapshot with no direction/target/stop-loss attached. Zero matches "
    "of any kind; nothing to fix."
)

PRIYA_YADUVANSHIIII_NOTES = (
    "Pure technical-analysis commentary and trading-psychology quotes — "
    "\"Nifty - Head & Shoulder pattern breakout failure\", \"23650 is "
    "Nifty's support and 23750 is Nifty's resistance level\", \"Mark PDH "
    "and PDL as strong resistance and support\" — never a BUY/SELL order "
    "with an entry trigger. Already parses to zero signals today with no "
    "phantom trades (no bug found, same 'no fix needed' outcome as the "
    "earlier Motilal Oswal specialist pass): support/resistance levels "
    "read like RE_SUPPORT/RE_CASH ABOVE-BELOW candidates but never pair "
    "with a BUY/SELL verb or CE/PE, so the channel-agnostic regexes "
    "correctly stay silent."
)


def set_styles(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    updates = [
        ('RAJESH PALVIYA', RAJESH_PALVIYA_NOTES),
        ('Bloomberg', BLOOMBERG_NOTES),
        ('Easy trading classes', EASY_TRADING_CLASSES_NOTES),
        ('Equitymaster', EQUITYMASTER_NOTES),
        ('Money creates Money', MONEY_CREATES_MONEY_NOTES),
        ('No Paid Service (@Anirbban public channel)', NO_PAID_SERVICE_NOTES),
        ('PL Technical Research', PL_TECHNICAL_RESEARCH_NOTES),
        ('Priya Yaduvanshiiii \U0001F4C8', PRIYA_YADUVANSHIIII_NOTES),
    ]
    for name, notes in updates:
        Channel.objects.filter(name=name).update(style='promo', style_notes=notes)


def unset_styles(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    names = [
        'RAJESH PALVIYA', 'Bloomberg', 'Easy trading classes', 'Equitymaster',
        'Money creates Money', 'No Paid Service (@Anirbban public channel)',
        'PL Technical Research', 'Priya Yaduvanshiiii \U0001F4C8',
    ]
    Channel.objects.filter(name__in=names).update(style='auto', style_notes='')


class Migration(migrations.Migration):

    dependencies = [
        ('traderacker', '0013_merge_20260914_0932'),
    ]

    operations = [
        migrations.RunPython(set_styles, unset_styles),
    ]
