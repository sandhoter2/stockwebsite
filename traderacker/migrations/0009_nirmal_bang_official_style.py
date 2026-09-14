# Sets Channel.style / style_notes for "NIRMAL BANG OFFICIAL" (the official
# Nirmal Bang broker research desk channel) so parse_signals picks the right
# parsing branch and future maintainers understand this channel's exact
# message format at a glance. Data-only migration — safely no-ops if the
# channel doesn't exist yet (fresh/test DB), and is idempotent (re-running
# it just overwrites with the same values).
from django.db import migrations

STYLE_NOTES = (
    "Official Nirmal Bang broker research desk. Multi-asset (equity cash, "
    "index/stock futures, index/stock/commodity options), heavily "
    "abbreviated, template-generated tips with a LOT of channel-specific "
    "shorthand the generic parser didn't originally understand:\n\n"
    "ENTRIES:\n"
    "1. Cash equity: \"1-2 Days Technical Call Buy BHARTIHEXA above 1555 "
    "with Stop Loss 1526 Target 1612 (ANALYST YADNESH)\" — already parsed "
    "correctly by the generic verb-first/RE_SUPPORT/RE_TARGET regexes.\n"
    "2. Futures with a compact expiry token glued (with no/optional space "
    "and an optional trailing \"T\") between the symbol and the FUT/"
    "FUTURE(S) keyword, in EITHER order: \"Sell AMBER  FUTURE 29SEPT below "
    "7170 with SL 7230, Target 7060\", \"Buy NIFTY 29SEP Future above "
    "23305\", \"BUY BANKNIFTY FUT 29 SEPT ABOVE 56120.4\". Needs RE_FUT — "
    "without it, the generic cash/verb-first regexes either grab the wrong "
    "symbol (the lazy word-bridge in RE_CASH latches onto an earlier "
    "unrelated all-caps filler word, e.g. \"DAYS\", when it can reach an "
    "ABOVE/BELOW+price stated in full caps) or a bogus partial-digit entry "
    "price parsed out of the expiry token itself (e.g. \"29\" from "
    "\"29SEP\", since NUM has no boundary against a directly-following "
    "letter).\n"
    "3. Options with the same compact expiry token between the root and "
    "the strike: \"Buy NIFTY 15SEP 23300 CE above 85 with SL 40 Target "
    "170\". RE_OPT's \\b boundary fails mid-word on \"15SEP\", so this "
    "shape is otherwise invisible to it and gets misread by RE_VERB_FIRST "
    "instead (again a partial-digit phantom entry). Needs RE_OPT_EXPIRY2.\n"
    "4. Commodity options with no expiry date, e.g. \"OPTION BUY CRUDEOIL "
    "9650 PE 395-385 SL BELOW 299 TG 520\" — RE_OPT itself parses these "
    "fine, but the option's own root+strike (\"BUY CRUDEOIL 9650\") was "
    "also being re-read by RE_VERB_FIRST as a second, bogus plain cash "
    "order on the same message. Fixed by having the plain-option loop "
    "(step 1) claim its root in option_roots like the expiry-aware option "
    "steps already did.\n\n"
    "ABBREVIATIONS (style-gated additions, checked only for this "
    "channel's style so no other channel's text can match on them): \"TG\" "
    "for TARGET (\"TG 520\", \"TG  9119-9000\") and \"ABV\" for ABOVE in a "
    "stop-loss clause (\"SL ABV 9677\").\n\n"
    "EXITS — this channel gives a raw price, never a rupee profit figure, "
    "across FOUR different close-out phrasings, all wired to "
    "parse_exit_price()/close_at_price() (which reads the trade's own "
    "stored entry, so no entry re-parsing is needed here):\n"
    "1. \"Book Partial Profit(s) in <SYM> at <PRICE[-PRICE2]>\" / \"Target "
    "Achieved in <SYM> at <PRICE>\" — <SYM> may itself carry the same "
    "compact expiry token (\"NIFTY 15SEP 23300 CE\", \"BANKNIFTY FUT 29 "
    "SEP\"), stripped by _normalize_close_symbol() back to the canonical "
    "trade string (\"NIFTY 23300 CE\", \"BANKNIFTY\"). A price range uses "
    "the first/lower number as the representative exit price.\n"
    "2. \"<SYM> CLOSE @<PRICE>\" for a plain option close, e.g. \"NIFTY "
    "23600CE CLOSE @31\".\n"
    "3. \"<SYM> SL Trigger(ed) @<PRICE>\" for a stop-loss hit, e.g. "
    "\"HINDALCO SL Triggered @1005\", \"VEDL 280CE SL TRIGGER @3\" — "
    "confirmed empirically unique to this channel across all 76 channels' "
    "tracked history, so left as an ungated/global pattern.\n"
    "4. The pre-existing generic \"BOOK PROFIT IN <SYM> @ <PRICE>\" also "
    "fires here directly (e.g. plain \"BOOK PROFIT\" wording).\n\n"
    "KNOWN DATA-QUALITY CAVEAT (not a parser bug, left as-is): this "
    "channel occasionally posts an incorrect \"Target Achieved\" naming "
    "the wrong strike, then corrects it with an \"ERRATA ...\" repost of "
    "the same event under the right strike. If the wrong strike happens "
    "to have its own genuinely Open trade, the erroneous message can "
    "close that real position at the wrong price before the correction "
    "even arrives (the correction itself is then a harmless no-op against "
    "an already-closed trade). Unwinding this would require the parser to "
    "understand \"ERRATA\" as retroactively invalidating a prior message, "
    "which no channel's parsing does today; observed once in the tracked "
    "history (NIFTY 23600 CE around Sept 11 2026).\n\n"
    "NOISE (no signal, verified harmless): promo YouTube live-session "
    "links and Zoom webinar registration posts, caught by is_promo(); the "
    "daily F&O ban-list post (bare all-caps ticker names with no verb/"
    "price, e.g. \"BANDHANBNK\\nINOXWIND\\n...\") never fires any regex "
    "since none of them carry a BUY/SELL/CE/PE/ABOVE/BELOW keyword; a "
    "\"BOOK PROFIT <price>-BUY <original order text>\" compound message "
    "(SILVERM, Sept 11 2026) restates the original commodity order right "
    "after a price level rather than a rupee profit — parse_profit() now "
    "recognizes the trailing \"-BUY\"/\"-SELL\" as a restated order and "
    "returns no profit rather than booking a wildly wrong ~₹237,400 "
    "'profit' (previously misread as a real rupee figure)."
)


def set_style(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    Channel.objects.filter(name='NIRMAL BANG OFFICIAL').update(
        style='mixed', style_notes=STYLE_NOTES)


def unset_style(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    Channel.objects.filter(name='NIRMAL BANG OFFICIAL').update(
        style='auto', style_notes='')


class Migration(migrations.Migration):

    dependencies = [
        ('traderacker', '0008_motilal_oswal_official_style'),
    ]

    operations = [
        migrations.RunPython(set_style, unset_style),
    ]
