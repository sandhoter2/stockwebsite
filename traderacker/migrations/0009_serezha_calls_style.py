# Sets Channel.style / style_notes for "Serezha Calls 😱" so parse_signals
# picks the right parsing branch and future maintainers understand this
# channel's exact message format at a glance. Data-only migration — safely
# no-ops if the channel doesn't exist yet (fresh/test DB), and is idempotent
# (re-running it just overwrites with the same values).
from django.db import migrations

STYLE_NOTES = (
    "Leveraged crypto-futures scalp signals (not options/cash/index despite "
    "the generic channel-agnostic parser being the shared code path) — 10x "
    "to 20x LONG/SHORT calls on altcoins (STX, NEAR, CRV, FIL, JUP, BCH, "
    "ONDO, DOGE, LINK, BNB, ETH). Two entry-signal shapes, both already "
    "handled by signals.py after this pass:\n\n"
    "1. \"<SYM> LONG 10x\\n\\n➡️Enter - 0.2570\\n\\n📌Target - 0.2596 - "
    "0.2642 - 0.2668 - 0.2835\\n\\n❌ Stop - 0.2440\" — matched by the "
    "generic RE_CRYPTO + RE_ENTER/RE_TARGET/RE_SUPPORT fallbacks already. "
    "Note the leverage multiplier is sometimes written with a Cyrillic "
    "'х' (U+0445) instead of Latin 'x' (e.g. \"STX LONG 10х\") — harmless, "
    "the (\\d+\\s*[Xx])? group is optional and unused by the parser.\n\n"
    "2. \"<SYM> – LONG\\n\\n✅Entry price: 0.08226\\n📌Targets: 0.08315/ "
    "0.08642 / 0.09025\\n❌Stop loss: 0.07829\" (DOGE, LINK) — symbol and "
    "LONG/SHORT joined by an em-dash \"–\" rather than a space, which the "
    "original RE_CRYPTO (space-only) silently missed entirely. Fixed by "
    "allowing an optional dash between the symbol and LONG/SHORT.\n\n"
    "3. A rarer bare-prose shape with no LONG/SHORT keyword at all, e.g. "
    "\"BNB is showing a local uptrend...\\n\\n✅Entry Price: 753.6\\n"
    "📌Target Prices: 761.1/ 774.2 / 799.5\\n❌Stop Loss Price: 730.7\" and "
    "\"#ETH\\n\\nETH has taken out the liquidity...\\n\\n✅Entry Price: "
    "2455\\n📌Target Prices: 2479 / 2546 / 2605\\n❌Stop Loss Price: 2379\". "
    "These also previously produced zero signal: RE_CRYPTO requires a "
    "LONG/SHORT keyword, and the \"Entry/Target/Stop-loss PRICE:\" wording "
    "(extra \"Price\"/\"Prices\" word before the colon) didn't match "
    "RE_ENTER/RE_TARGET/RE_SUPPORT either. Fixed narrowly: those three "
    "regexes now tolerate an optional PRICE(S) word, and a new fallback "
    "(only when no other signal matched) looks for a bare KNOWN crypto "
    "ticker plus all three of Entry/Target/Stop-loss PRICE labels present "
    "together, inferring direction from target-vs-entry (never from "
    "sentiment words like \"uptrend\") — deliberately gated tight (whitelist "
    "ticker AND all three labels) so an ordinary prose mention of a coin on "
    "some other channel can't become a phantom trade.\n\n"
    "FOLLOW-UP / STATUS-UPDATE POSTS (no new signal — verified correct): "
    "this channel re-posts the original \"<SYM> LONG 10x\" header as the "
    "first line of nearly every status update (\"STX LONG 10x\\n1 TP ⚡️\", "
    "\"JUP LONG 10x\\n...Unfortunately, our position got stopped out...\"). "
    "Before this pass, RE_CRYPTO matched that repeated header on its own "
    "with entry=None, and parse_signals' upsert key is (channel, trade, "
    "entry) — since None != the real entry price, EVERY such follow-up "
    "created a second phantom Open \"<SYM>\" trade row with all fields "
    "blank (confirmed empirically: STX/CRV/FIL/JUP/BCH each had exactly "
    "one such duplicate in the tracked history, 5 total). Fixed by "
    "dropping any crypto-classified signal that still has no entry price "
    "after all fill attempts, consistent with the parser's existing "
    "\"no confident match -> no trade\" philosophy. (Checked: no other of "
    "the 76 channels had ever produced an entry-less crypto signal, so "
    "this filter is a no-op everywhere else.)\n\n"
    "EXITS: the channel narrates outcomes in prose (\"stopped out\", "
    "\"Two targets secured\", \"hit the first target and then closed at "
    "entry\", \"+43%\") but — in the tracked history — never once posts an "
    "absolute rupee/dollar profit figure or a clean \"EXIT <SYM> @ "
    "<PRICE>\"/\"BOOK PROFIT IN <SYM> @ <PRICE>\" close-out. parse_exit() "
    "does flag \"stopped out\" as an exit keyword (e.g. the JUP follow-up), "
    "but parse_signals.book() only ever closes a trade when a profit "
    "figure is ALSO present, so these positions correctly stay Open per "
    "the pipeline's \"only close on explicit text\" rule rather than being "
    "force-closed on a percentage/prose-only claim this parser can't turn "
    "into a verified realized amount. Left unimplemented deliberately: "
    "converting \"+43%\" into a money figure would need the entry price "
    "and no stated position size, and guessing risks a fabricated realized "
    "number.\n\n"
    "NOISE (verified no false positive): the opening \"3-5% PER TRADE / "
    "82% win rate / t.me/+... invite link / #ad\" post is an ad for an "
    "unrelated signal service, caught by is_promo() (\"join\"-adjacent "
    "invite link, no BUY/SELL/LONG/SHORT/CE/PE trade verb). General market "
    "commentary posts (CryptoQuant/Bitmine mentions, weekend greetings) "
    "produce no signal since they lack Entry/Target/Stop-loss wording."
)


def set_style(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    Channel.objects.filter(name='Serezha Calls 😱').update(
        style='crypto', style_notes=STYLE_NOTES)


def unset_style(apps, schema_editor):
    Channel = apps.get_model('traderacker', 'Channel')
    Channel.objects.filter(name='Serezha Calls 😱').update(
        style='auto', style_notes='')


class Migration(migrations.Migration):

    dependencies = [
        ('traderacker', '0008_motilal_oswal_official_style'),
    ]

    operations = [
        migrations.RunPython(set_style, unset_style),
    ]
