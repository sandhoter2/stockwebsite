import datetime as dt

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from traderacker.models import (Channel, PaperTrade, Trade, UserPreference,
                                Watchlist, trust_tier, wilson_lower_bound)


class TrackerApiTests(TestCase):
    """Covers the date-range-aware stats/breakdown endpoints (QA §4)."""

    def setUp(self):
        self.user = User.objects.create_user('tester', password='pw12345!')
        self.client.force_login(self.user)
        self.ch = Channel.objects.create(peer='-1001', name='Chan A', short='A')
        self.ch2 = Channel.objects.create(peer='-1002', name='Chan B', short='B')
        today = dt.date(2026, 9, 10)
        # Chan A: 2 closed wins, 1 closed loss, 1 open, 1 undated closed
        Trade.objects.create(channel=self.ch, date=today - dt.timedelta(days=1),
                             trade='W1', entry=100, realized=50, status='Closed')
        Trade.objects.create(channel=self.ch, date=today,
                             trade='W2', entry=200, realized=80, status='Closed')
        Trade.objects.create(channel=self.ch, date=today - dt.timedelta(days=30),
                             trade='L1', entry=150, realized=-40, status='Closed')
        Trade.objects.create(channel=self.ch, date=today,
                             trade='O1', entry=90, unrealized=10, status='Open')
        Trade.objects.create(channel=self.ch, date=None,
                             trade='UNDATED', entry=10, realized=5, status='Closed')
        # Chan B: 1 closed win
        Trade.objects.create(channel=self.ch2, date=today,
                             trade='B1', entry=60, realized=30, status='Closed')

    def test_stats_requires_auth(self):
        self.client.logout()
        r = self.client.get('/api/tracker/stats/')
        self.assertIn(r.status_code, (401, 403))

    def test_stats_all(self):
        d = self.client.get('/api/tracker/stats/').json()
        self.assertEqual(d['trades'], 6)
        self.assertEqual(d['wins'], 4)      # W1, W2, UNDATED, B1
        self.assertEqual(d['losses'], 1)    # L1
        self.assertEqual(d['open'], 1)
        self.assertEqual(d['realized'], 125)  # 50+80-40+5+30
        self.assertEqual(d['unrealized'], 10)
        self.assertEqual(d['success_rate'], 80.0)  # 4/5 booked

    def test_stats_scoped_to_channel(self):
        d = self.client.get(f'/api/tracker/stats/?channel={self.ch2.id}').json()
        self.assertEqual(d['trades'], 1)
        self.assertEqual(d['realized'], 30)
        self.assertEqual(d['success_rate'], 100.0)

    def test_stats_date_range_excludes_old_and_undated(self):
        r = self.client.get('/api/tracker/stats/?date_from=2026-09-09&date_to=2026-09-10')
        d = r.json()
        # W1(9/9), W2(9/10), O1(9/10), B1(9/10) → 4; L1(8/11) & UNDATED excluded
        self.assertEqual(d['trades'], 4)
        self.assertEqual(d['wins'], 3)
        self.assertEqual(d['losses'], 0)

    def test_stats_invalid_date_returns_400(self):
        r = self.client.get('/api/tracker/stats/?date_from=notadate')
        self.assertEqual(r.status_code, 400)

    def test_stats_reversed_range_returns_400(self):
        r = self.client.get('/api/tracker/stats/?date_from=2026-09-10&date_to=2026-09-01')
        self.assertEqual(r.status_code, 400)

    def test_stats_non_integer_channel_returns_400(self):
        r = self.client.get('/api/tracker/stats/?channel=abc')
        self.assertEqual(r.status_code, 400)

    def test_breakdown_groups_by_channel(self):
        rows = self.client.get('/api/tracker/stats/breakdown/').json()['results']
        by_name = {r['name']: r for r in rows}
        self.assertEqual(by_name['Chan A']['trades'], 5)
        self.assertEqual(by_name['Chan A']['wins'], 3)
        self.assertEqual(by_name['Chan A']['booked'], 4)
        self.assertEqual(by_name['Chan A']['success_rate'], 75.0)
        self.assertEqual(by_name['Chan B']['trades'], 1)

    def test_breakdown_respects_date_range(self):
        rows = self.client.get(
            '/api/tracker/stats/breakdown/?date_from=2026-09-09'
        ).json()['results']
        by_name = {r['name']: r for r in rows}
        self.assertEqual(by_name['Chan A']['trades'], 3)  # W1, W2, O1
        # L1 (8/11) and UNDATED excluded → only 2 booked wins for A
        self.assertEqual(by_name['Chan A']['booked'], 2)

    def test_breakdown_empty_when_no_trades_in_range(self):
        rows = self.client.get(
            '/api/tracker/stats/breakdown/?date_from=2030-01-01'
        ).json()['results']
        self.assertEqual(rows, [])

    def test_summary_endpoint(self):
        d = self.client.get('/api/tracker/summary/').json()
        self.assertEqual(d['channels'], 2)
        self.assertEqual(d['trades'], 6)
        self.assertEqual(d['open_trades'], 1)


class SignalParserTests(TestCase):
    """Unit tests for traderacker.signals (the message → trade parser)."""

    def test_cash_above_with_support_and_view(self):
        from traderacker.signals import parse_message
        text = ('BLUESTARCO \n\n BLUESTARCO CASH ABOVE 1570\n\n SUPPORT 1470\n\n'
                ' VIEW 1800\n\n HOLDING \n\n Disclaimer :-\nAbove calls are Not '
                'Buy or Sell Levels,These opinions are for educational purposes only.')
        sigs = parse_message(text)
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'BLUESTARCO')
        self.assertEqual(s['direction'], 'BUY')
        self.assertEqual(s['entry'], 1570.0)
        self.assertEqual(s['stop_loss'], 1470.0)
        self.assertEqual(s['target'], 1800.0)
        self.assertEqual(s['status'], 'Open')

    def test_breakout_above(self):
        from traderacker.signals import parse_message
        sigs = parse_message('BLUESTARCO BREAKOUT ABOVE 1600')
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['entry'], 1600.0)
        self.assertEqual(sigs[0]['direction'], 'BUY')

    def test_option_with_premium(self):
        from traderacker.signals import parse_message
        sigs = parse_message('BANKNIFTY 57000 PE @ 505')
        self.assertTrue(any(s['trade'] == 'BANKNIFTY 57000 PE' and s['entry'] == 505.0
                            and s['direction'] == 'PUT (down)' for s in sigs), sigs)

    def test_option_plain(self):
        from traderacker.signals import parse_message
        sigs = parse_message('NEW LOCK CALL\n\nNIFTY 24000 CE\n\nENTRY 90\nTGT 115\nS/T 80')
        n = [s for s in sigs if s['trade'] == 'NIFTY 24000 CE']
        self.assertEqual(len(n), 1)
        self.assertEqual(n[0]['entry'], 90.0)
        self.assertEqual(n[0]['target'], 115.0)
        self.assertEqual(n[0]['stop_loss'], 80.0)

    def test_junk_messages_produce_nothing(self):
        from traderacker.signals import parse_message
        self.assertEqual(parse_message('170'), [])
        self.assertEqual(parse_message('Good Morning Traders ✨\n507\n09:53 PM'), [])
        self.assertEqual(parse_message('Account handling work 👍❤️'), [])
        self.assertEqual(parse_message(''), [])

    def test_profit_amounts(self):
        from traderacker.signals import parse_profit
        self.assertEqual(parse_profit('PAYTM 1720 CE booked 64700++ PROFIT'), 64700.0)
        self.assertEqual(parse_profit('PROFIT 5000 on NIFTY'), 5000.0)
        self.assertEqual(parse_profit('TATAPOWER 370 CE\n2,175+ PROFIT'), 2175.0)
        self.assertIsNone(parse_profit('High accuracy = Real Profit'))
        self.assertIsNone(parse_profit('Today account handling work done'))

    def test_verb_first_nirmal(self):
        from traderacker.signals import parse_message
        sigs = parse_message('1-2 Days Technical Call Buy BHARTIHEXA above 1555 '
                             'with Stop Loss 1526 Target 1612 (ANALYST).')
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['trade'], 'BHARTIHEXA')
        self.assertEqual(sigs[0]['entry'], 1555.0)
        self.assertEqual(sigs[0]['target'], 1612.0)
        self.assertEqual(sigs[0]['stop_loss'], 1526.0)
        self.assertEqual(sigs[0]['asset_class'], 'stock')

    def test_verb_first_with_share_qty(self):
        # broker-style: "BUY <SYMBOL> <N> shares at <PRICE>." (Angel One Research)
        from traderacker.signals import parse_message
        sigs = parse_message('🟢 BUY AMBUJACEM 1 shares at 575.10.\n\n'
                             'Message : SL  563.8 TGT 594')
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['trade'], 'AMBUJACEM')
        self.assertEqual(sigs[0]['entry'], 575.1)
        self.assertEqual(sigs[0]['stop_loss'], 563.8)
        self.assertEqual(sigs[0]['target'], 594.0)

    def test_verb_first_with_cmp(self):
        # broker-style: "BUY <SYMBOL>" then "CMP <PRICE>" on the next line
        # (Motilal Oswal)
        from traderacker.signals import parse_message
        sigs = parse_message('MOSt Overnight  \n\nBUY SGMART  \n\nCMP 852.05 \n'
                             'SL 826 \nTGT 906.4')
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['trade'], 'SGMART')
        self.assertEqual(sigs[0]['entry'], 852.05)
        self.assertEqual(sigs[0]['stop_loss'], 826.0)
        self.assertEqual(sigs[0]['target'], 906.4)

    def test_option_with_expiry_date_and_lots(self):
        # broker-style option order with an expiry date between the index and
        # strike, and a lot-size clause before the premium (Angel One Research)
        from traderacker.signals import parse_message
        sigs = parse_message('🟢 BUY NIFTY 03 JUL 25 25700 CE 1 lots at 109.00.\n\n'
                             'Expiry : 03-Jul-2025\n\nMessage : SL 94 TGT 135')
        n = [s for s in sigs if s['trade'] == 'NIFTY 25700 CE']
        self.assertEqual(len(n), 1)
        self.assertEqual(n[0]['entry'], 109.0)
        self.assertEqual(n[0]['direction'], 'CALL (up)')
        self.assertEqual(n[0]['stop_loss'], 94.0)
        self.assertEqual(n[0]['target'], 135.0)

    def test_option_with_expiry_date_no_phantom_root_trade(self):
        # the broker-style expiry order ("BUY NIFTY 03 JUL 25 25700 CE ...")
        # used to also match the looser verb-first regex, misreading the
        # expiry day-of-month ("03") as a second, phantom "NIFTY" cash entry
        # (Angel One Research)
        from traderacker.signals import parse_message
        sigs = parse_message('BUY BANKNIFTY 31 JUL 25 59000 CE 1 lots at 356.00.\n\n'
                             'Expiry : 31-Jul-2025\n\nMessage : SL 317 TGT 420')
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['trade'], 'BANKNIFTY 59000 CE')
        self.assertEqual(sigs[0]['entry'], 356.0)

    def test_exit_price_book_profit_in_phrasing(self):
        # "BOOK PROFIT IN <SYMBOL> @ <PRICE>" is this channel's other exit
        # phrasing alongside "EXIT ... @ PRICE" (Angel One Research)
        from traderacker.signals import parse_exit_price
        self.assertEqual(parse_exit_price('BOOK PROFIT IN GMDCLTD @422.5'),
                         ('GMDCLTD', 422.5))
        self.assertEqual(parse_exit_price('BOOK PROFIT IN RAYMOND @ 636.5'),
                         ('RAYMOND', 636.5))

    def test_exit_price_book_ignores_words_not_symbols(self):
        # "BOOK PROFIT IN 57000 PE @ 583.5" has no confident symbol (the
        # option strike, not a ticker) and "EXIT POSITIONS @106" is a
        # generic word, not a symbol — both should stay unparsed rather
        # than spawn a bogus close-out (Angel One Research)
        from traderacker.signals import parse_exit_price
        self.assertIsNone(parse_exit_price('BOOK PROFIT IN 57000 PE @ 583.5'))
        self.assertIsNone(parse_exit_price('EXIT POSITIONS @106'))

    def test_option_signal_not_reopened_by_its_own_exit_message(self):
        # "EXIT BANKNIFTY 58500 CE @ 499" would previously ALSO match the
        # plain option regex (RE_OPT) as if it were a fresh order at entry
        # 499, leaving a phantom duplicate Open trade behind alongside the
        # correct close-out of the original position (Angel One Research)
        from traderacker.signals import parse_message, parse_exit_price
        sigs = parse_message('EXIT BANKNIFTY 58500 CE @ 499')
        self.assertEqual(sigs, [])
        self.assertEqual(parse_exit_price('EXIT BANKNIFTY 58500 CE @ 499'),
                         ('BANKNIFTY 58500 CE', 499.0))

    def test_conviction_delivery_idea_full_signal(self):
        # "Conviction Delivery Idea" is this channel's swing/delivery-tip
        # header, identical CMP/SL/TGT body shape to "MOSt Overnight"
        # (Motilal Oswal - Official)
        from traderacker.signals import parse_message
        sigs = parse_message(
            'Conviction Delivery Idea  \n\nBUY EXAMPLETICK  \n\nCMP 500.25  \n'
            'SL 480 \nTGT 540\n- Range breakout on daily chart.\n\n'
            'Disclaimer- https://ftp.motilaloswal.com/emailer/Marketdiary/'
            'Disclaimer/Disclaimer.pdf')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'EXAMPLETICK')
        self.assertEqual(s['direction'], 'BUY')
        self.assertEqual(s['entry'], 500.25)
        self.assertEqual(s['stop_loss'], 480.0)
        self.assertEqual(s['target'], 540.0)
        self.assertEqual(s['asset_class'], 'stock')

    def test_daily_digest_technical_pick_not_parsed(self):
        # the daily "3 Things That Will Decide the Market Today" digest ends
        # with a "Technical Pick" naming a mixed-case, sometimes multi-word
        # company name ("Sai Life Sciences Ltd") rather than the ALL-CAPS
        # ticker this codebase relies on for symbol detection, and gives no
        # stop-loss — deliberately left unparsed rather than guessing a
        # ticker (Motilal Oswal - Official; see migration 0008 style_notes)
        from traderacker.signals import parse_message
        text = (
            '📊 3 Things That Will Decide the Market Today\n\n'
            'Fundamental Picks (for more than a year)\n'
            '1.Titan- Target 6000 (19%)\n2. Granules- Target 1010(21%)\n\n'
            'Technical Pick -\nSAI LIFE SCIENCES Ltd BUY\n'
            'Previous Close: 1587\nTarget: 1667\nPotential upside: ~5%'
        )
        self.assertEqual(parse_message(text), [])

    def test_join_now_promo_and_prose_exit_word_are_harmless(self):
        # bare "Join Now" campaign links are promo (no trade verb); a quiz/
        # engagement post that happens to use the word "exit" in prose must
        # not parse as a signal or exit (Motilal Oswal - Official)
        from traderacker.signals import parse_message, is_promo, parse_exit
        promo_text = ('Join Now : https://www.motilaloswal.com/campaign/'
                     'Registrationoffers/e2e/SubBrokers/e2e-telegram.html')
        self.assertTrue(is_promo(promo_text))
        self.assertEqual(parse_message(promo_text), [])
        quiz_text = ('Gap up but close below the open = trapped sellers '
                    'were waiting for a bounce to exit. The earnings beat '
                    'gave them the gift.')
        self.assertEqual(parse_message(quiz_text), [])
        self.assertTrue(parse_exit(quiz_text))  # matches RE_EXIT in prose...
        from traderacker.signals import parse_profit
        self.assertIsNone(parse_profit(quiz_text))  # ...but no profit figure,
        # so parse_signals' book() never acts on it (profit is None -> no-op)

    def test_comma_strike_range(self):
        from traderacker.signals import parse_message
        sigs = parse_message('✅SENSEX 73,900 PE✅\n₹250-320✅✅')
        self.assertEqual(sigs[0]['trade'], 'SENSEX 73900 PE')
        self.assertEqual(sigs[0]['entry'], 250.0)
        self.assertEqual(sigs[0]['target'], 320.0)
        self.assertEqual(sigs[0]['asset_class'], 'option')

    def test_crypto_long_short(self):
        from traderacker.signals import parse_message
        sigs = parse_message('ONDO LONG 20x\n\n➡️Enter - 0.3514\n\n'
                             '📌Target - 0.3550 - 0.3614\n\n❌ Stop - 0.3336')
        self.assertEqual(sigs[0]['trade'], 'ONDO')
        self.assertEqual(sigs[0]['direction'], 'BUY')
        self.assertEqual(sigs[0]['entry'], 0.3514)
        self.assertEqual(sigs[0]['asset_class'], 'crypto')

    def test_crypto_em_dash_long_short(self):
        # Serezha Calls' other entry-signal shape: symbol and LONG/SHORT
        # joined by an em-dash rather than a space, with "Entry price:" /
        # "Targets:" / "Stop loss:" labels instead of Enter/Target/Stop.
        from traderacker.signals import parse_message
        sigs = parse_message(
            'AVAX – SHORT\n\n✅Entry price: 42.500\n'
            '📌Targets: 42.100/ 41.600 / 40.900\n❌Stop loss: 43.800\n\n'
            'AVAX swept the upper liquidity pool, expecting a correction.')
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['trade'], 'AVAX')
        self.assertEqual(sigs[0]['direction'], 'SELL')
        self.assertEqual(sigs[0]['entry'], 42.5)
        self.assertEqual(sigs[0]['target'], 42.1)
        self.assertEqual(sigs[0]['stop_loss'], 43.8)
        self.assertEqual(sigs[0]['asset_class'], 'crypto')

    def test_crypto_bare_symbol_price_labels_no_long_short(self):
        # Serezha Calls' rarest shape: no LONG/SHORT keyword anywhere, just
        # prose naming a known crypto ticker plus fully-labeled Entry/Target
        # Price(s)/Stop Loss Price lines. Direction is inferred from
        # target-vs-entry, never from the prose wording itself.
        from traderacker.signals import parse_message
        sigs = parse_message(
            '#SOL\n\nSOL has taken out liquidity at the bottom of the range, '
            'expecting the same move at the top.\n\n'
            '✅Entry Price: 145.20\n📌Target Prices: 147.50 / 150.10 / 153.00\n'
            '❌Stop Loss Price: 141.80')
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['trade'], 'SOL')
        self.assertEqual(sigs[0]['direction'], 'BUY')
        self.assertEqual(sigs[0]['entry'], 145.2)
        self.assertEqual(sigs[0]['target'], 147.5)
        self.assertEqual(sigs[0]['stop_loss'], 141.8)
        self.assertEqual(sigs[0]['asset_class'], 'crypto')

    def test_crypto_prose_mention_without_price_labels_stays_unparsed(self):
        # A bare crypto ticker mentioned in market commentary, with no
        # Entry/Target/Stop-loss labels at all, must never become a phantom
        # trade (the tight 3-label gate on the bare-symbol fallback).
        from traderacker.signals import parse_message
        sigs = parse_message(
            'According to CryptoQuant, the recent rise in ETH has been '
            'driven by short covering rather than new demand.')
        self.assertEqual(sigs, [])

    def test_crypto_repeat_header_followup_produces_no_phantom_signal(self):
        # A status-update post that re-quotes the original "<SYM> LONG 10x"
        # header (this channel's normal follow-up shape) must not create a
        # second, entry-less signal — that upserts as a phantom duplicate
        # Open trade in parse_signals (upsert key is channel+trade+entry).
        from traderacker.signals import parse_message
        sigs = parse_message('STX LONG 10x\n1 TP secured ⚡')
        self.assertEqual(sigs, [])
        sigs2 = parse_message(
            'JUP LONG 10x\nHello friends\n\n'
            'Unfortunately, our position got stopped out. '
            'We will make up for the loss fast.')
        self.assertEqual(sigs2, [])

    def test_exit_detection(self):
        from traderacker.signals import parse_exit
        self.assertTrue(parse_exit('2,175+ PROFIT💰 SAFE BOOK HERE'))
        self.assertTrue(parse_exit('TARGET HIT, exiting now'))
        self.assertFalse(parse_exit('Fresh entry NIFTY 24000 CE'))

    def test_exit_price_detection(self):
        from traderacker.signals import parse_exit_price
        self.assertEqual(parse_exit_price('EXIT RTNINDIA @ 63.3'), ('RTNINDIA', 63.3))
        self.assertEqual(parse_exit_price('EXIT FROM NIFTY 25600 CE@92'),
                         ('NIFTY 25600 CE', 92.0))
        self.assertEqual(parse_exit_price('Exit from Banknifty 59000 ce @ 364'),
                         ('BANKNIFTY 59000 CE', 364.0))
        self.assertIsNone(parse_exit_price('TARGET HIT, exiting now'))
        self.assertIsNone(parse_exit_price('Fresh entry NIFTY 24000 CE'))

    def test_fresh_breakout_lowercase(self):
        # "SYMBOL fresh breakout above/below N" is Stockpro Online's own
        # lower/mixed-case level phrasing (the codebase's usual RE_CASH is
        # case-sensitive on "ABOVE"/"BELOW"/"BREAKOUT" to avoid matching
        # ordinary prose in other channels, so it never fires for this one).
        # Only the first word becomes the trade symbol for a multi-word name.
        from traderacker.signals import parse_message
        sigs = parse_message('LUMINO fresh breakout above 112')
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['trade'], 'LUMINO')
        self.assertEqual(sigs[0]['entry'], 112.0)
        self.assertEqual(sigs[0]['direction'], 'BUY')

        sigs2 = parse_message('APOLLO MICRO fresh breakout above 418')
        self.assertEqual(len(sigs2), 1)
        self.assertEqual(sigs2[0]['trade'], 'APOLLO')
        self.assertEqual(sigs2[0]['entry'], 418.0)

    def test_shared_research_recap_signal(self):
        # "We shared the research ... it looks good above N" is Stockpro
        # Online's retrospective recap/social-proof post — sometimes the
        # only record of an earlier call's entry level in the tracked
        # history, so it's treated as a real signal.
        from traderacker.signals import parse_message
        text = ('✅MILKYMIST  🔥 - We shared the research 2nd September '
                '2026 only that it looks good above 237\n\n'
                'Today it made a high of 292.75, Stock has delivered '
                'potential 23.52% upmove in few days only')
        sigs = parse_message(text)
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['trade'], 'MILKYMIST')
        self.assertEqual(sigs[0]['entry'], 237.0)
        self.assertEqual(sigs[0]['direction'], 'BUY')

    def test_ladder_shape_absolute_targets(self):
        # Stockpro Online's DOMINANT shape (not caught by the narrow
        # RE_FRESH_BREAKOUT/RE_SHARED_RESEARCH fix above): a multi-line
        # "POSITIONAL/SCALPING ... TRADE|RESEARCH" header, symbol on its
        # own line, "Looks Good ABOVE <ladder>", "SL <stop>", "Targets
        # <ladder>", "Hold <duration>". Absolute-price targets (no "points
        # from entry" suffix) — only the first rung of each ladder is kept.
        from traderacker.signals import parse_message
        text = (
            'POSITIONAL RESEARCH\n\n'
            'GOOD STOCK LTD\n\n'
            'Looks good above 628-629\n\n'
            'SL 600\n\n'
            'Targets 640-650-660-675-685-700\n\n'
            'Hold few weeks\n\n'
            'Please consult your financial advisor before investing.\n'
            'All research is for educational purposes only.'
        )
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        sig = sigs[0]
        self.assertEqual(sig['trade'], 'GOOD STOCK LTD')
        self.assertEqual(sig['entry'], 628.0)
        self.assertEqual(sig['stop_loss'], 600.0)
        self.assertEqual(sig['target'], 640.0)
        self.assertEqual(sig['direction'], 'BUY')
        self.assertEqual(sig['status'], 'Open')

    def test_ladder_shape_points_from_entry_targets(self):
        # The same shape's other target-ladder unit: an offset ("N points
        # from entry") rather than an absolute price — must be ADDED to
        # entry, never compared to entry as if it were an absolute level
        # (a raw offset like "5" read as an absolute target would silently
        # produce a nonsensical below-entry "target").
        from traderacker.signals import parse_message
        text = (
            'POSITIONAL TRADE\n\n'
            'SOME FINANCE\n'
            'Looks Good above 378\n\n'
            'SL 355\n\n'
            'TARGETS 5-10-15-20-25-30 points from entry\n\n'
            'Hold few weeks\n\n'
            'Please consult your financial advisor before investing.'
        )
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        sig = sigs[0]
        self.assertEqual(sig['trade'], 'SOME FINANCE')
        self.assertEqual(sig['entry'], 378.0)
        self.assertEqual(sig['stop_loss'], 355.0)
        self.assertEqual(sig['target'], 383.0)  # 378 + 5, not 5.0

    def test_ladder_shape_sl_or_accumulation_zone(self):
        # "SL or Accumulation Zone <price>" is this channel's stop-loss
        # variant phrasing seen on some ladder-shape posts.
        from traderacker.signals import parse_message
        text = (
            'SCALPING TRADE\n\n'
            'SOME MICRO LTD\n'
            'Looks Good ABOVE 405-407\n\n'
            'SL or Accumulation Zone 380\n\n'
            'Targets 412-420-430\n\n'
            'Hold few days'
        )
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['trade'], 'SOME MICRO LTD')
        self.assertEqual(sigs[0]['stop_loss'], 380.0)

    def test_ladder_shape_short_alias_in_parens(self):
        # A trailing "(SHORTALIAS)" gives the channel's own short ticker,
        # used instead of concatenating the full multi-word name.
        from traderacker.signals import parse_message
        text = (
            'POSITIONAL RESEARCH\n\n'
            'SOME GOOD NAME LTD (SGNL)\n\n'
            'Looks good above 100\n\n'
            'SL 90\n\n'
            'Targets 110-120-130\n\n'
            'Hold few weeks'
        )
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['trade'], 'SGNL')

    def test_ladder_shape_style_gated_to_mixed(self):
        # The ladder shape must never fire for a channel whose style isn't
        # 'mixed' — same gating discipline as the Nirmal Bang-specific
        # 1c/1d expiry-token patterns above.
        from traderacker.signals import parse_message
        text = (
            'POSITIONAL RESEARCH\n\n'
            'GOOD STOCK LTD\n\n'
            'Looks good above 628-629\n\n'
            'SL 600\n\n'
            'Targets 640-650-660\n\n'
            'Hold few weeks'
        )
        self.assertEqual(parse_message(text, style=None), [])
        self.assertEqual(parse_message(text, style='auto'), [])

    def test_ladder_shape_never_fabricates_a_close(self):
        # Per the no-auto-close product rule: only an explicit close-out
        # phrase (SL hit / crossed all targets) may close a trade. A
        # "MADE A HIGH OF" or "LOCKED IN UPPER CIRCUIT" follow-up on an
        # already-open ladder call is pure price-tracking, not an exit —
        # parse_exit/parse_exit_price must both stay silent on it.
        from traderacker.signals import parse_exit, parse_exit_price
        for text in ('GOODSTOCKLTD MADE A HIGH OF 674.85\U0001F680\U0001F680',
                     'GOODSTOCKLTD LOCKED IN UPPER CIRCUIT \U0001F680'):
            self.assertFalse(parse_exit(text))
            self.assertIsNone(parse_exit_price(text))

    def test_ladder_shape_explicit_crossed_all_targets_with_price_closes(self):
        # "<SYMBOL> crossed all targets, currently at <PRICE>" is one of
        # the rare explicit close-outs this channel does post — it names
        # both the symbol and a price, so it's safe to close at. The far
        # more common "<SYMBOL> crossed all targets" with NO price is
        # deliberately left unhandled (never fabricate an exit price).
        from traderacker.signals import parse_exit_price
        self.assertEqual(
            parse_exit_price('GOODSTOCKLTD crossed all targets, currently at 690'),
            ('GOODSTOCKLTD', 690.0))
        self.assertIsNone(parse_exit_price('GOODSTOCKLTD crossed all Targets'))
        self.assertIsNone(parse_exit_price('GOODSTOCKLTD crossed all targets today'))

    def test_made_a_high_of_is_not_a_signal_or_exit(self):
        # a pure price-tracking follow-up on an already-open call — no
        # BUY/breakout keyword (no new signal) and no close-out wording
        # (RE_EXIT never fires), so the trade correctly stays Open per the
        # no-auto-close product rule (Stockpro Online).
        from traderacker.signals import parse_message, parse_exit
        text = '✅RAYMOND MADE A HIGH OF 974.85🚀🚀'
        self.assertEqual(parse_message(text), [])
        self.assertFalse(parse_exit(text))

    def test_oi_dump_produces_no_signal(self):
        # strike-wise NIFTY/BANKNIFTY long/short open-interest dumps have no
        # ALL-CAPS-ticker-with-adjacent-price shape the parser recognizes
        # (Stockpro Online).
        from traderacker.signals import parse_message
        text = ('NIFTY\n23200 -\nLongs - 3.10L (Intraday - 1.95L)\n'
                'Shorts - 66225 (Intraday - 60634)\n\nData negative.\n'
                'VIX 5.17% up.')
        self.assertEqual(parse_message(text), [])

    def test_promo_messages_are_skipped(self):
        from traderacker.signals import parse_message, is_promo
        self.assertTrue(is_promo('Ganesh offer opens here, valid for first 50 slots only'))
        self.assertEqual(
            parse_message('Veegaland IPO final verdict — price band, lot size, '
                          'apply now https://youtu.be/x'), [])
        self.assertTrue(parse_message('Buy BHARTIHEXA above 1555 Target 1612'))

    # -- NIRMAL BANG OFFICIAL (style='mixed') --------------------------------
    # This channel glues a compact day+month expiry token ("29SEP", "15SEP")
    # directly between the symbol and the FUT/strike, which the generic
    # regexes can't place — RE_FUT/RE_OPT_EXPIRY2 and the TG/ABV/close-out
    # abbreviations below are all gated behind style='mixed' so no other
    # channel's parsing is affected (see migration 0009's style_notes).

    def test_future_order_with_compact_expiry_token(self):
        from traderacker.signals import parse_message
        # expiry token AFTER the FUT keyword, lowercase ABOVE/BELOW
        sigs = parse_message(
            'Sell EXAMPLESTK  FUTURE 29SEPT below 7170 with SL 7230, '
            'Target 7060(ANALYST AMIT). Visit our website for disclosure. '
            '(Nirmal Bang).', style='mixed')
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['trade'], 'EXAMPLESTK')
        self.assertEqual(sigs[0]['direction'], 'SELL')
        self.assertEqual(sigs[0]['entry'], 7170.0)
        self.assertEqual(sigs[0]['stop_loss'], 7230.0)
        self.assertEqual(sigs[0]['target'], 7060.0)
        # expiry token BEFORE the FUT keyword, uppercase ABOVE — this shape
        # used to also spawn a bogus "DAYS" trade (RE_CASH's lazy word-
        # bridge latching onto the earlier all-caps filler word) plus a
        # phantom real-symbol entry at a partial-digit price parsed out of
        # the expiry token itself
        sigs2 = parse_message(
            '1-2 DAYS Call Technical call BUY BANKNIFTY FUT 29 SEPT ABOVE '
            '56120.4 with SL 55750 Target 57100 (ANALYST SWATI). Visit our '
            'website for disclosure (Nirmal Bang)', style='mixed')
        self.assertEqual(len(sigs2), 1)
        self.assertEqual(sigs2[0]['trade'], 'BANKNIFTY')
        self.assertEqual(sigs2[0]['direction'], 'BUY')
        self.assertEqual(sigs2[0]['entry'], 56120.4)
        self.assertEqual(sigs2[0]['asset_class'], 'index')

    def test_option_order_with_compact_expiry_token(self):
        from traderacker.signals import parse_message
        sigs = parse_message(
            'Intraday Derivatives Call Buy NIFTY 15SEP 23300 CE above 85 '
            'with SL 40 Target 170 (ANALYST NIRAV) Visit our website for '
            'disclosure (Nirmal Bang)', style='mixed')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'NIFTY 23300 CE')
        self.assertEqual(s['direction'], 'CALL (up)')
        self.assertEqual(s['entry'], 85.0)
        self.assertEqual(s['stop_loss'], 40.0)
        self.assertEqual(s['target'], 170.0)
        self.assertEqual(s['asset_class'], 'option')

    def test_commodity_option_no_expiry_no_phantom_cash_order(self):
        # "OPTION BUY CRUDEOIL 9650 PE ..." previously also spawned a bogus
        # second "BUY CRUDEOIL 9650" cash/commodity signal, since the
        # option's own root wasn't excluded from the looser regexes. Also
        # exercises the "TG"/"ABV" target/stop-loss abbreviations.
        from traderacker.signals import parse_message
        sigs = parse_message(
            'OPTION BUY CRUDEOIL 9650 PE 395-385 SL BELOW 299 TG 520',
            style='mixed')
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['trade'], 'CRUDEOIL 9650 PE')
        self.assertEqual(sigs[0]['target'], 520.0)
        sigs2 = parse_message(
            'RISKY SELL CRUDEOIL 9448-9468 SL ABV 9677\nTG  9119-9000',
            style='mixed')
        self.assertEqual(len(sigs2), 1)
        self.assertEqual(sigs2[0]['trade'], 'CRUDEOIL')
        self.assertEqual(sigs2[0]['stop_loss'], 9677.0)
        self.assertEqual(sigs2[0]['target'], 9119.0)

    def test_book_partial_profit_and_target_achieved_close_events(self):
        # this channel never gives a rupee profit figure or the generic
        # "EXIT SYM @ PRICE" shape — it names the symbol (sometimes with the
        # same compact expiry token as the entry) and a raw exit price
        # (occasionally a small range; the first number is used).
        from traderacker.signals import parse_exit_price
        self.assertEqual(
            parse_exit_price(
                '1-2 Days Technical Call Book Partial profits in '
                'EXAMPLESTK at 387.7-389,  Target 396, BUY Call initiated '
                'at 382.4 (ANALYST YADNESH). Visit our website for '
                'disclosure. (Nirmal Bang).'),
            ('EXAMPLESTK', 387.7))
        self.assertEqual(
            parse_exit_price(
                'Intraday Derivatives Call Target Achieved in NIFTY 15SEP '
                '23300 CE at 170, Call initiated at 85 (ANALYST NIRAV) '
                'Visit our website for disclosure (Nirmal Bang)'),
            ('NIFTY 23300 CE', 170.0))
        self.assertEqual(
            parse_exit_price(
                '1-2 DAYS Technical Call book partial profit in BANKNIFTY '
                'FUT 29 SEP @ 56500-56520  Target 57100 BUY call initiated '
                '56120.40 (ANALYST SWATI). Visit our website for '
                'disclosure (Nirmal Bang).'),
            ('BANKNIFTY', 56500.0))

    def test_option_close_and_sl_trigger_close_events(self):
        from traderacker.signals import parse_exit_price, parse_message
        # "SYM CLOSE @PRICE" — also must not spawn a phantom fresh option
        # order at the close price (previously the message-level "@ price"
        # premium fallback mis-filled a new Open trade from the close price)
        self.assertEqual(
            parse_exit_price('NIFTY 23600CE CLOSE @31 Visit our website '
                             'for disclosure. (Nirmal Bang)'),
            ('NIFTY 23600 CE', 31.0))
        self.assertEqual(
            parse_message('NIFTY 23600CE CLOSE @31 Visit our website for '
                          'disclosure. (Nirmal Bang)', style='mixed'), [])
        # "SYM SL Trigger(ed) @PRICE" stop-loss hit
        self.assertEqual(
            parse_exit_price('1-2 Days HINDALCO SL Triggered @1005 .  '
                             'Visit our website for disclosure. (Nirmal '
                             'Bang).'),
            ('HINDALCO', 1005.0))
        self.assertEqual(
            parse_exit_price('1-2 days call VEDL 280CE SL TRIGGER @3 '
                             'Visit our website for disclosure. (Nirmal '
                             'Bang).'),
            ('VEDL 280 CE', 3.0))

    def test_book_profit_price_restated_order_is_not_a_rupee_profit(self):
        # "BOOK PROFIT 237400-BUY SILVERM ..." restates the original
        # commodity order right after a price level — that number is a
        # price, not a rupee profit total, so parse_profit() must not treat
        # it as one (it previously booked a bogus ~₹237,400 "profit").
        from traderacker.signals import parse_profit, parse_exit
        text = ('BOOK PROFIT 237400-BUY EXAMPLEM 235700-400 SL BELOW '
                '233400 TG 238000')
        self.assertIsNone(parse_profit(text))
        self.assertTrue(parse_exit(text))  # RE_EXIT still matches "BOOK
        # PROFIT" in prose, but book() no-ops since profit is None

    def test_options_train_end_of_day_recap_closes_at_true_final_profit(self):
        # Options Train ( SEBI REGISTERED) posts an "ENTRY TO EXIT" recap,
        # sometimes as the ONLY message for a trade (no separate "@ premium"
        # entry line ever posted) -- see migration 0009 style_notes. The
        # option leg + entry price is still parsed by the shared RE_OPT
        # regex; separately, parse_exit() must recognize the "<entry> TO
        # <exit>" + nearby PROFIT wording as an explicit close so
        # parse_signals' book() locks in the real final profit instead of
        # leaving the trade open forever with only peak_profit set.
        from traderacker.signals import parse_message, parse_exit, parse_profit
        text = 'BSE 3500  CE\n\n85 TO 114\n\n5,800+++++ PROFIT 💰💰💰\n\nROI 34%\n\n🥳'
        sigs = parse_message(text)
        self.assertEqual(sigs[0]['trade'], 'BSE 3500 CE')
        self.assertEqual(sigs[0]['entry'], 85.0)
        self.assertTrue(parse_exit(text))
        self.assertEqual(parse_profit(text), 5800.0)

    def test_options_train_to_range_recap_without_profit_word_is_not_an_exit(self):
        # a handful of OTHER channels post superficially similar "<option
        # leg>\n<price> TO <price>" recaps but phrase their close-out as
        # "...POINT DONE...% ROI DONE" with no literal PROFIT word nearby
        # (e.g. "BANKNIFTY 55700 CALL 940 TO 1020..... 80 POINT DONE 8% ROI
        # DONE") -- these must stay untouched by the Options Train fix.
        from traderacker.signals import parse_exit
        text = 'SUPER DUPER DAY OVER\n\nBANKNIFTY 55700 CALL 940 TO 1020..... 80 POINT DONE 8% ROI DONE'
        self.assertFalse(parse_exit(text))

    def test_options_train_stray_profit_number_is_not_mistaken_for_entry(self):
        # a one-line "Premium Call" post with no "@ premium" marker at all,
        # e.g. "IDEA 15 CE\n\n3500++ Profit" -- the shared option regex used
        # to grab the *profit* figure across the blank line as if it were
        # the entry price (entry=3500). Now left as entry=None: there is no
        # confident entry price in this shape, and no exit phrase either,
        # so it stays Open per the "never guess a close" product rule.
        from traderacker.signals import parse_message
        sigs = parse_message('Premium Call ❤️❤️\n\nIDEA 15 CE \n\n3500++ Profit❤️❤️❤️')
        self.assertEqual(sigs[0]['trade'], 'IDEA 15 CE')
        self.assertIsNone(sigs[0]['entry'])

    def test_options_train_safe_can_book_is_not_a_generic_exit(self):
        # "SAFE CAN BOOK" is this channel's other running-update phrasing
        # (interchangeable with "SAFE BOOK HERE" in the channel's own
        # usage) but was deliberately NOT added to the shared RE_EXIT: doing
        # so verifiably made realized profit *more* understated for this
        # channel (it would lock in the first, usually smallest, booking
        # figure). Confirmed unique to this channel, so this is a no-op for
        # every other channel either way.
        from traderacker.signals import parse_exit
        self.assertFalse(parse_exit('94++ 🔥🔥🔥\n\n6,175++ PROFIT💰💰💰\n\nSAFE CAN BOOK'))

    def test_underscore_joined_strike_entry_range(self):
        # "Buy NIFTY _23650PE Above 190-200" joins the index name to the
        # strike+right with an underscore rather than a space, and "Above
        # 190-200" is an entry TRIGGER range (not an entry/target pair like
        # other channels' "₹250-320" shorthand) — the first number is the
        # entry, the real target comes later from "Target : ..." (Stock
        # Thunder)
        from traderacker.signals import parse_message
        sigs = parse_message('Buy NIFTY\xa0 _23800PE Above 210-220\n\n'
                             'Target : 260/330/380\n\nStoploss : Paid')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'NIFTY 23800 PE')
        self.assertEqual(s['direction'], 'PUT (down)')
        self.assertEqual(s['entry'], 210.0)
        self.assertEqual(s['target'], 260.0)
        self.assertIsNone(s['stop_loss'])
        self.assertEqual(s['asset_class'], 'option')

    def test_progress_recap_does_not_duplicate_open_position(self):
        # "<price> TO <price>#<SYM> <strike><right>" is a running LTP recap
        # on an already-open leg, posted with no BUY/SELL verb — it used to
        # also match the plain option regex as if it were a fresh order at
        # entry=None, leaving a phantom duplicate Trade behind alongside the
        # correctly-entered original (Stock Thunder). "GAINING RS-" is this
        # channel's own profit phrasing, fed into parse_profit() via
        # RE_GAINING; the "TARGET ALMOST/FULL HIT" wording is deliberately
        # not an explicit close-out (no SOLD/BOOKED/"TARGET HIT" as a literal
        # phrase), so it must not trip parse_exit either.
        from traderacker.signals import parse_message, parse_profit, parse_exit
        text = ('210 TO 248#NIFTY 23800PE \n\nGAINING RS- 3800/ 2 LOTS \n\n'
               'FIRST TARGET ALMOST HIT 🎯 \n\nBOOK PARTIAL PROFIT OR TRAIL SL ✅')
        self.assertEqual(parse_message(text), [])
        self.assertEqual(parse_profit(text), 3800.0)
        self.assertFalse(parse_exit(text))

    def test_positional_stock_option_trade_no_phantom_cash_trade(self):
        # "POSITIONAL STOCK OPTION TRADE\n\nBUY <SYM> <strike> CE|PE ABOVE
        # <price> TRG - <t1>-<t2>-<t3> SL PAID" used to also fire the looser
        # ABOVE/BELOW cash regex twice: once treating the "POSITIONAL"
        # label itself as a phantom symbol, and once treating the option's
        # own strike as a bogus cash entry price for the real ticker
        # (Stock Thunder). "TRG" needed adding as a RE_TARGET alias
        # alongside VIEW/TARGETS?/TGT/SHT to pick up the first of the
        # dash-separated target list.
        from traderacker.signals import parse_message
        sigs = parse_message('POSITIONAL STOCK OPTION TRADE  \n\n'
                             'BUY RELIANCE 3000 CE ABOVE 45 TRG - 55-65-80 '
                             'SL PAID \n\nSEP EXPIRY')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'RELIANCE 3000 CE')
        self.assertEqual(s['entry'], 45.0)
        self.assertEqual(s['target'], 55.0)
        self.assertEqual(s['asset_class'], 'option')

    # --- batch2 specialist pass (Ashika Calls, MarketWolf, Short To Mid
    # Term, THEBULLOPTIONS, Swing Trader Vishal, Stocky Mind) ---

    def test_ashika_futures_paren_expiry_cmp(self):
        # "BUY <SYM> FUT (<expiry>)CMP <range> SL <sl> TGT <tgt>" — the
        # parenthetical expiry annotation between FUT and CMP used to make
        # RE_VERB_FIRST miss the CMP price entirely (entry stayed None).
        from traderacker.signals import parse_message
        sigs = parse_message('BUY HDFCLIFE FUT (30 DEC)CMP 640-644 SL 618 TGT 690',
                             style='mixed')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'HDFCLIFE')
        self.assertEqual(s['entry'], 640.0)
        self.assertEqual(s['direction'], 'BUY')

    def test_ashika_paren_expiry_range_cmp_does_not_truncate_target(self):
        # "<ROOT> <STRIKE> CE (<expiry>) CMP <low>-<high> ... TGT <price>" —
        # the generic bare dash-range fallback's 20-char window gets
        # truncated by the parenthetical (e.g. "150-160" -> "150-16"),
        # which used to misread "16" as the target instead of leaving it
        # blank for the later explicit "TGT 240" to fill correctly.
        from traderacker.signals import parse_message
        sigs = parse_message(
            'HIGH RISK CALL: BUY NIFTY 25100 CE (23 SEPT) CMP 150-160 SL 120 TGT 240',
            style='mixed')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['entry'], 150.0)
        self.assertEqual(s['target'], 240.0)
        self.assertNotEqual(s['target'], 16.0)

    def test_ashika_two_char_lt_ticker(self):
        # "LT" is one character short of the shared SYM pattern's 3-char
        # floor — special-cased for this channel rather than globally.
        from traderacker.signals import parse_message
        sigs = parse_message('BUY LT CMP 3850-3857 SL 3740 TGT 4035', style='mixed')
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['trade'], 'LT')
        self.assertEqual(sigs[0]['entry'], 3850.0)

    def test_ashika_lowercase_index_option_paren_expiry(self):
        # Ashika occasionally writes the index name lower/mixed-case, with
        # the same parenthetical-expiry-before-CMP shape as the futures case.
        from traderacker.signals import parse_message
        sigs = parse_message('BUY Nifty  24500 PE (JAN20) CMP 70 to 68  SL 40 TGT 110',
                             style='mixed')
        opt = [s for s in sigs if s['trade'] == 'NIFTY 24500 PE']
        self.assertEqual(len(opt), 1)
        self.assertEqual(opt[0]['entry'], 70.0)
        self.assertEqual(opt[0]['asset_class'], 'option')

    def test_ashika_book_profit_cmp_close(self):
        # Ashika's close-outs use "CMP" as the price marker instead of the
        # "AT"/"@" RE_CLOSE_EVENT originally supported (Nirmal Bang's
        # phrasing) — this extension is ungated (parse_exit_price has no
        # style parameter) but verified safe across the full corpus.
        from traderacker.signals import parse_exit_price
        self.assertEqual(parse_exit_price('BOOK PARTIAL PROFIT IN ESCORTS  CMP 3623'),
                         ('ESCORTS', 3623.0))

    def test_marketwolf_option_hidden_behind_subscription_price(self):
        # The "@<price> only!" on line 1 is the paid-tip SUBSCRIPTION price,
        # not the option premium — a naive "SYMBOL @ PRICE" read would
        # misattribute it. The real entry is the first number of the "BUY :
        # <low>-<high>" range three lines later.
        from traderacker.signals import parse_message
        text = ('Trade SENSEX @9,900 only!\n\nIndex : SENSEX\n\n'
               'OPTION:  76500 PUT (PE) 15th MAY\n\n\U0001F3F9 BUY : 410-440\n\n'
               '\U0001F3AF Target & Stop Loss : RA Team To Update')
        sigs = parse_message(text, style='options')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'SENSEX 76500 PE')
        self.assertEqual(s['entry'], 410.0)
        self.assertNotEqual(s['entry'], 9900.0)
        self.assertEqual(s['direction'], 'PUT (down)')

    def test_marketwolf_commentary_produces_nothing(self):
        # Daily "Hunting Zones"/status posts carry price-ish numbers but no
        # structured Index/OPTION/BUY block, and close-outs give a status/%
        # with no price or strike — both correctly produce no signal.
        from traderacker.signals import parse_message
        self.assertEqual(parse_message(
            'Key CRUDE OIL levels\n- If it Breaks above 8,700 then we may see '
            'the Upside Movement.', style='options'), [])
        self.assertEqual(parse_message(
            'GOLD MINI at ₹6,000 | SL Triggered\n\nInstrument: GOLD MINI\n'
            'Status: -20% Loss', style='options'), [])

    def test_short_to_mid_term_hashtag_entry_ladder(self):
        # Symbol comes from the trailing hashtag, not the display name
        # before it (which can be an abbreviated/unrelated-looking variant).
        from traderacker.signals import parse_message
        text = ('\U0001F195⬇️\U0001F4E2\n\n\U0001F4B9  WHIRLPOOL OF INDIA\n\n'
               '\U0001F387  CMP-  1100-1102\n\n\U0001F3A0 UPSIDE RESISTANCE  - '
               '1140-1190-1250\n\n#WHIRLPOOL\n\n\U0001F4A5 DISCLAIMER')
        sigs = parse_message(text, style='cash')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'WHIRLPOOL')
        self.assertEqual(s['entry'], 1100.0)
        self.assertEqual(s['target'], 1140.0)

    def test_short_to_mid_term_retrospective_recap(self):
        # States both entry and already-hit exit in one line; recorded Open
        # (not Closed) — see style_notes for why this codebase's
        # exit-price path can't close a same-message create-and-close.
        from traderacker.signals import parse_message
        sigs = parse_message('#IOC 94 TO 145+\U0001F680\U0001F680\U0001F680   '
                             '3RD TGT DONE ✅✅', style='cash')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'IOC')
        self.assertEqual(s['entry'], 94.0)
        self.assertEqual(s['target'], 145.0)
        self.assertEqual(s['status'], 'Open')

    def test_thebulloptions_repost_does_not_mint_phantom_trades(self):
        # The channel reposts the SAME leg many times as a running LTP
        # ticker; only the "BUY ABOVE <price>" trigger message should get a
        # real entry — every other repost must stay entry=None so it
        # collapses into the same row instead of minting a new phantom
        # Trade per repost.
        from traderacker.signals import parse_message
        trigger = parse_message('\U0001F4CA SENSEX 74000 PE (04 JUN)\n\n'
                                '\U0001F4C8 BUY ABOVE 370\n\n\U0001F3AF TARGET PREMIUM\n\n'
                                '☠️SL - PREMIUM', style='options')
        self.assertEqual(len(trigger), 1)
        self.assertEqual(trigger[0]['trade'], 'SENSEX 74000 PE')
        self.assertEqual(trigger[0]['entry'], 370.0)

        repost = parse_message('\U0001F4CA SENSEX 74000 PE (04 JUN)\n420', style='options')
        self.assertEqual(len(repost), 1)
        self.assertIsNone(repost[0]['entry'])

        milestone = parse_message('\U0001F4CA SENSEX 74000 PE (04 JUN)\nFIRST TARGET DONE ✅',
                                  style='options')
        self.assertEqual(len(milestone), 1)
        self.assertIsNone(milestone[0]['entry'])

    def test_thebulloptions_doesnt_affect_other_options_channels(self):
        # The full-remainder ABOVE/BELOW fallback added for THEBULLOPTIONS
        # is gated on style == 'options', which Options Train and Stock
        # Thunder also use — confirm a plain broker-style option order is
        # unaffected (still gets its @-premium entry, not an unrelated
        # later ABOVE/BELOW word).
        from traderacker.signals import parse_message
        sigs = parse_message('BUY NIFTY 03 JUL 25 25700 CE 1 lots at 109.00.\n\n'
                             'Message : SL 94 TGT 135 (safe entries above 25650 only)',
                             style='options')
        opt = [s for s in sigs if 'NIFTY' in s['trade'] and s['asset_class'] == 'option']
        self.assertTrue(opt)
        self.assertEqual(opt[0]['entry'], 109.0)

    def test_vishal_bought_hashtag_mixed_case(self):
        # Ticker hashtags are often lower/mixed case; uppercased on capture.
        from traderacker.signals import parse_message
        sigs = parse_message('Bought #vascon 63.8\n\n- Huge volume breakout + Retest\n\n'
                             'SL Below 60 ❗️', style='cash')
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['trade'], 'VASCON')
        self.assertEqual(sigs[0]['entry'], 63.8)

    def test_stocky_mind_recap_direction_from_range(self):
        # Direction is inferred from which side of the "N to M" range is
        # higher: a down-move recap is a SELL, an up-move recap is a BUY.
        from traderacker.signals import parse_message
        down = parse_message('⚡️ CRUDEOIL\n\n9085 to 8920 | 5R+\n\n'
                             'Locked the majority gains \U0001F4B0', style='mixed')
        self.assertEqual(len(down), 1)
        self.assertEqual(down[0]['trade'], 'CRUDEOIL')
        self.assertEqual(down[0]['direction'], 'SELL')
        self.assertEqual(down[0]['asset_class'], 'commodity')

        up = parse_message('⚡️ APOLLOPIPE | Swing Trade\n\n429 to 454+ \U0001F4A5 | 6%+',
                           style='mixed')
        self.assertEqual(len(up), 1)
        self.assertEqual(up[0]['direction'], 'BUY')

    # -- Batch 3: Stock Gainers, Bnf_unicorn, Ritvi Taneja, Samco ----------

    def test_stock_gainers_cmp_support_for_entry(self):
        # "<SYMBOL>\n\nCMP <price>\n\nSupport <price>\n\nFor <range>" is
        # Stock Gainers' dominant forward-call shape.
        from traderacker.signals import parse_message
        text = 'DIAMOND POWER\n\nCMP 356\n\nSupport 340\n\n\nFor 385-410'
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'DIAMOND POWER')
        self.assertEqual(s['entry'], 356.0)
        self.assertEqual(s['stop_loss'], 340.0)
        self.assertEqual(s['target'], 385.0)

    def test_stock_gainers_recap_ignores_live_analysis_digest(self):
        # The "N to M" recap shape requires the symbol alone on its own
        # line; the daily digest crams "SYMBOL price TO price" onto one
        # line per stock with no blank-line gap and must never match (it
        # would otherwise mint dozens of phantom duplicate trades). The
        # digest's individual lines DO still parse as ordinary option
        # orders via the unrelated, pre-existing RE_OPT path -- this test
        # is only about RE_STOCKGAINERS_RECAP itself never matching them.
        from traderacker.signals import parse_message, RE_STOCKGAINERS_RECAP
        recap = parse_message('Astra Micro\n\n1440 to 1480 \U0001F525', style='mixed')
        self.assertEqual(len(recap), 1)
        self.assertEqual(recap[0]['trade'], 'ASTRA MICRO')
        self.assertEqual(recap[0]['entry'], 1440.0)
        self.assertEqual(recap[0]['target'], 1480.0)

        digest = ('Stock Gainers (SEBI REGISTERED)\n\U0001F31F Live Analysis of 16th JUNE\n\n'
                  '1. OPTION ANALYSIS\n\n\nPGEL 520CE CE 14 TO 20\U0001F525\n'
                  'BANDHANBANK 212.5CE 7.5 TO 9.75\U0001F525')
        self.assertIsNone(RE_STOCKGAINERS_RECAP.search(digest))

    def test_bnfunicorn_bullet_breakout_call(self):
        # Nivisha Verma's "✅"-bulleted chart-commentary shape needs an
        # explicit above/breakout-level trigger to produce a signal.
        from traderacker.signals import parse_message
        text = ('PIDILITE IND\n✅Breakout above 3280+ possible\n✅Strong chart\n'
                '✅After breakout support will be 3160/3050\n'
                '✅Target 3350/3475/3600++\n✅Keep on radar')
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'PIDILITE IND')
        self.assertEqual(s['entry'], 3280.0)
        self.assertEqual(s['stop_loss'], 3160.0)
        self.assertEqual(s['target'], 3350.0)

        # a support+target call with no stated entry trigger stays unparsed
        no_entry = parse_message(
            'AEROFLEX\n\U0001F91D Promising chart breakout\n✅Strong weekly close\n'
            '✅Support 160 & 147\n✅looks good for 190/200+\n✅Keep on radar',
            style='mixed')
        self.assertEqual(no_entry, [])

    def test_ritvi_taneja_arrow_bullet_breakout_call(self):
        # Same bullet shape as Bnf_unicorn but with "➡" markers.
        from traderacker.signals import parse_message
        text = ('HINDZINC\n➡ Re-creating Pole & Flag Pattern\n'
                '➡ Breakout possible above 700\n➡ Support near 630\n'
                '➡ Keep on radar')
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'HINDZINC')
        self.assertEqual(s['entry'], 700.0)
        self.assertEqual(s['stop_loss'], 630.0)

    def test_ritvi_taneja_symline_support_shape(self):
        # "<SYMBOL> <PRICE>" alone on the first line, with a support figure
        # and a "Can hit <ladder>" target elsewhere in the message.
        from traderacker.signals import parse_message
        text = 'SBIN 1011\nSupport 992\n\nAvg 1000-995\n\nCan hit 1025/1038/1050\n\nWeak below 992 closing'
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'SBIN')
        self.assertEqual(s['entry'], 1011.0)
        self.assertEqual(s['stop_loss'], 992.0)
        self.assertEqual(s['target'], 1025.0)

    def test_samco_recommendation_alert_structured_block(self):
        # Samco's formal broker template: "Symbol:" is the real ticker,
        # "CMP:"/"Stop loss:"/"Target:" self-explanatory.
        from traderacker.signals import parse_message
        text = ('RECOMMENDATION ALERT \U0001F514\n\nStock Name: Pfizer Limited\n'
                'Symbol: PFIZER\nRating: Buy \U0001F7E2\nCMP: ₹4130\n'
                'Stop loss: ₹3890\nTarget: ₹4545\nDuration: 5-10 Days\n'
                'Trade Date: 21-03-2025 02:21 PM\nTrade Type: Swing Trader\n'
                'Name of RA: Om Mehra\n\nNote: Buy PFIZER at 4130 SL 3890 TGT 4545\n\n'
                'Disclaimer: https://sam-co.in/6j/ Samco Securities Ltd')
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)  # block + Note dedup to one row
        s = sigs[0]
        self.assertEqual(s['trade'], 'PFIZER')
        self.assertEqual(s['entry'], 4130.0)
        self.assertEqual(s['stop_loss'], 3890.0)
        self.assertEqual(s['target'], 4545.0)

    def test_samco_option_glued_expiry_symbol(self):
        # "<ROOT><DD><MON><STRIKE>CE|PE" all glued together (e.g.
        # "AUBANK25DEC980PE") is Samco's dominant options-order shape --
        # the generic RE_VERB_FIRST fallback misreads the glued expiry's
        # own digits ("25") as a bogus cash entry price if this doesn't
        # claim the symbol first.
        from traderacker.signals import parse_message
        text = ('RECOMMENDATION ALERT \U0001F514\n\nStock Name: AU SMALL FINANCE BANK LTD\n'
                'Symbol: AUBANK25DEC980PE\nRating: Buy \U0001F7E2\nCMP: ₹10.5\n'
                'Stop loss: ₹7.3\nTarget: ₹14.2\nDuration: 1-5 Days\n'
                'Trade Type: Positional Stock Options\nName of RA: Om Mehra\n\n'
                'Note: Buy AUBANK 25DEC980PE at 10.5 SL 7.3 TGT 14.2\n\n'
                'Disclaimer: https://sam-co.in/6j/ Samco Securities Ltd')
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'AUBANK 980 PE')
        self.assertEqual(s['entry'], 10.5)
        self.assertNotEqual(s['entry'], 25.0)

    def test_samco_weekly_numeric_expiry_no_phantom_duplicate(self):
        # A strike with no letter month code at all ("NIFTY2540323300CE")
        # must not also spawn a blank second row under the generic
        # RE_OPT/RE_OPT_INDEX_CI >6-digit-strike misread.
        from traderacker.signals import parse_message
        text = ('RECOMMENDATION ALERT \U0001F514\n\nStock Name: NIFTY\n'
                'Symbol: NIFTY2540323300CE\nRating: Buy \U0001F7E2\nCMP: ₹90\n'
                'Stop loss: ₹65\nTarget: ₹130\nDuration: Intraday\n'
                'Trade Type: Index Option Intraday Strategy\nName of RA: Dhupesh Dhameja\n\n'
                'Disclaimer: https://sam-co.in/6j/ Samco Securities Ltd')
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['entry'], 90.0)

    def test_samco_month_abbreviation_root_rejected(self):
        # A DDMMM expiry token with a SPACE before the strike ("BANKNIFTY
        # MAR 49500 CE") makes RE_OPT's simple root+digits shape backtrack
        # onto the month letters themselves as a bogus "MAR" ticker with no
        # price data at all -- confirmed the same defect pre-existed (and
        # is now fixed) in other channels, not just Samco.
        from traderacker.signals import parse_message
        sigs = parse_message(
            'Intraday Index Option Sell BANKNIFTY MAR 49500 CE @ 361-365 SL 407 TGT 300',
            style='mixed')
        self.assertFalse(any(s['trade'].startswith('MAR ') for s in sigs), sigs)

    def test_darshan_option_entry_target_open(self):
        # "Target Open" means no stated numeric target -- kept blank
        # rather than guessed.
        from traderacker.signals import parse_message
        text = ('Nifty 26100 Ce (13 Jan Expiry)\nCmp 151\nTarget Open\nStoploss 120\n\n'
                '*Keep Proper Risk Management\nCalculate your RISK First')
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'NIFTY 26100 CE')
        self.assertEqual(s['entry'], 151.0)
        self.assertIsNone(s['target'])
        self.assertEqual(s['stop_loss'], 120.0)
        self.assertEqual(s['direction'], 'CALL (up)')

    def test_darshan_recap_cash_and_option(self):
        from traderacker.signals import parse_message
        cash = parse_message('Sail from 129.3 to 141\n\nAlmost 10% Returns in 12 Trading Sessions',
                             style='mixed')
        self.assertEqual(len(cash), 1)
        self.assertEqual(cash[0]['trade'], 'SAIL')
        self.assertEqual(cash[0]['direction'], 'BUY')
        self.assertEqual(cash[0]['target'], 141.0)

        opt = parse_message('Sensex 74900 Ce From 5 to 160\n\n32x', style='mixed')
        self.assertEqual(len(opt), 1)
        self.assertEqual(opt[0]['trade'], 'SENSEX 74900 CE')
        self.assertEqual(opt[0]['direction'], 'CALL (up)')

    def test_finsarthi_lowercase_option_order(self):
        # Roughly half this channel's real calls write ce/pe/put in lower
        # or mixed case, invisible to every case-sensitive option regex.
        # Requires the full SL+TARGET structure so it never fires on this
        # channel's frequent "<strike> put writer"/"<strike> call writer"
        # market-positioning commentary.
        from traderacker.signals import parse_message
        text = 'Bank nifty 55000 ce at 1100 sl 1000 tgt 1180 and 1250\nIf someone holding'
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'BANK NIFTY 55000 CE')
        self.assertEqual(s['entry'], 1100.0)
        self.assertEqual(s['stop_loss'], 1000.0)
        self.assertEqual(s['target'], 1180.0)

    def test_finsarthi_put_writer_commentary_not_a_signal(self):
        from traderacker.signals import parse_message
        sigs = parse_message('24200 put writer are still there\nSo Nifty post CAS 24219',
                             style='mixed')
        self.assertEqual(sigs, [])

    def test_mystocks_bought_hashtag_dominant_shape(self):
        # Mystocks.in's dominant entry shape is the existing generic
        # RE_VISHAL_BOUGHT "Bought #SYM price" pattern -- it just needed
        # Channel.style set to 'cash' to be consulted at all.
        from traderacker.signals import parse_message
        text = 'Bought #Kotyark 1020\nSL Below 960\n\nPlay for strong earnings'
        sigs = parse_message(text, style='cash')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'KOTYARK')
        self.assertEqual(s['entry'], 1020.0)
        self.assertEqual(s['stop_loss'], 960.0)

    def test_sl_percentage_not_read_as_price(self):
        # "SL 1%" / "Target 4-6%" are risk-sizing percentages, not absolute
        # prices -- a real SL/target is never immediately followed by "%".
        from traderacker.signals import parse_message
        text = 'Bought #MVELECTRO 615\n\nSL 1%\n\nTarget 4-6%'
        sigs = parse_message(text, style='cash')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['entry'], 615.0)
        self.assertIsNone(s['stop_loss'])
        self.assertIsNone(s['target'])

    def test_nasdaqmasters_lowercase_forex_signal(self):
        # About half this channel's real calls write buy/sell in lower or
        # mixed case, and often state a dual "entry+entry" price joined by
        # "+" -- only the first number is kept as the entry.
        from traderacker.signals import parse_message
        sigs = parse_message('XAUUSD sell 4335+4340\nSL 4350\n\nTP 4330\nTP 4325',
                             style='mixed')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'XAUUSD')
        self.assertEqual(s['direction'], 'SELL')
        self.assertEqual(s['entry'], 4335.0)
        self.assertEqual(s['stop_loss'], 4350.0)

    def test_nasdaqmasters_can_buy_with_phrasing(self):
        from traderacker.signals import parse_message
        sigs = parse_message('*GOLD CAN BUY WITH 4402\n#GOLD BUY \n\nTP 1 HIT 20+ pips',
                             style='mixed')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'GOLD')
        self.assertEqual(s['direction'], 'BUY')
        self.assertEqual(s['entry'], 4402.0)

    def test_nasdaqmasters_uppercase_shape_unaffected(self):
        # The pre-existing uppercase-only shape (RE_VERB_FIRST/RE_BUYSELL)
        # already covered this -- confirms the new lower/mixed-case shape
        # doesn't produce a duplicate second row for the same call.
        from traderacker.signals import parse_message
        sigs = parse_message('XAUUSD BUY 4408+4402\nXAUUSD ☑️\n2 TP HIT 80 PIPS',
                             style='mixed')
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['entry'], 4408.0)

    def test_paisa20_premium_tip_entry_to_target(self):
        # 20PAISA..COM's dominant option-tip shape: the entry premium AND
        # the level it already ran to sit on the next non-blank line,
        # joined by "To". Mixed-case "Nifty"/"Sensex" root, only visible
        # via RE_OPT_INDEX_CI (style == 'mixed').
        from traderacker.signals import parse_message
        text = 'PREMIUM ✅✅\n\n\n\n\nNifty 22500CE\n\n\n\n\n175 To 260++💙💙✅✅'
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'NIFTY 22500 CE')
        self.assertEqual(s['entry'], 175.0)
        self.assertEqual(s['target'], 260.0)

    def test_paisa20_done_of_the_day_recap_per_leg_prices(self):
        # A "Done Of The Day" recap restates several legs in ONE message,
        # each with its own "@ <entry> To <exit>" — regression check that
        # each leg gets ITS OWN price pair rather than every leg collapsing
        # onto the first leg's "@" value via the shared message-level
        # RE_PREMIUM fallback.
        from traderacker.signals import parse_message
        text = ('✍ Done Of The Day ✍\n\n\n✅Nifty 22500CE @ 175 To 260+\n\n\n'
                '✅Nifty 22600CE @ 177 To 193\n\n\n✅Nifty 22600PE @ 170 To 188+')
        sigs = parse_message(text, style='mixed')
        by_trade = {s['trade']: s for s in sigs}
        self.assertEqual(by_trade['NIFTY 22500 CE']['entry'], 175.0)
        self.assertEqual(by_trade['NIFTY 22500 CE']['target'], 260.0)
        self.assertEqual(by_trade['NIFTY 22600 CE']['entry'], 177.0)
        self.assertEqual(by_trade['NIFTY 22600 CE']['target'], 193.0)
        self.assertEqual(by_trade['NIFTY 22600 PE']['entry'], 170.0)
        self.assertEqual(by_trade['NIFTY 22600 PE']['target'], 188.0)

    def test_paisa20_no_price_closure_leg_not_phantom_filled(self):
        # A recap leg that states NO price at all ("@ SL Taken", "@ 20
        # Point SL") must not be silently stamped with an unrelated leg's
        # "@ <price>" from earlier in the same multi-leg message -- the
        # channel-agnostic bug this guarded against (RE_OPT_NO_PRICE_CLOSE).
        from traderacker.signals import parse_message
        text = ('✍️ Done Of The Day ✍️\n\n\n✅Nifty 23950CE @ 170 To 196+\n\n\n'
                '✅Nifty 24000CE @ 20 Point SL \n\n\n✅BNF 55900CE @ SL Taken')
        sigs = parse_message(text, style='mixed')
        trades = {s['trade'] for s in sigs}
        self.assertIn('NIFTY 23950 CE', trades)
        self.assertNotIn('NIFTY 24000 CE', trades)
        self.assertNotIn('BNF 55900 CE', trades)

    def test_paisa20_good_above_entry_and_sl(self):
        text = 'Nifty 22400PE Good Above @ 172\n\n\nSl : 152'
        from traderacker.signals import parse_message
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'NIFTY 22400 PE')
        self.assertEqual(s['entry'], 172.0)
        self.assertEqual(s['stop_loss'], 152.0)
        self.assertIsNone(s['target'])

    def test_paisa20_strong_support_commentary_not_a_trade(self):
        # Plain index-level commentary with no trade content ("Nifty Strong
        # Support\n\n24000 To 24050") must not be misread as a trade via
        # the shared Stock Gainers/Ritvi Taneja RE_STOCKGAINERS_RECAP shape
        # (its first word "NIFTY" is a real index root, so the existing
        # first-word-only STOCKGAINERS_DENY check alone doesn't catch it).
        from traderacker.signals import parse_message
        sigs = parse_message('Nifty Strong Support\n\n\n\n24000 To 24050', style='mixed')
        self.assertEqual(sigs, [])

    def test_stockizen_futures_short_still_matches_trailing_deny_word(self):
        # Stockizen Research's genuine futures call also ends in a
        # STOCKGAINERS_DENY word ("SHORT") -- confirms the new trailing-
        # phrase check added for 20PAISA..COM's "STRONG SUPPORT" only
        # blocks that exact two-word tail, not every candidate ending in
        # any single deny word.
        from traderacker.signals import parse_message
        text = ('INTRADAY \n\nNIFTY SEP FUT SHORT\n\n24145 TO 24040 🔥🔥🔥\n\n'
                'TARGET 1 - 24040 DONE ✅✅\n\nENJOY #FUTUREX TRADE')
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'NIFTY SEP FUT SHORT')
        self.assertEqual(s['direction'], 'SELL')
        self.assertEqual(s['entry'], 24145.0)
        self.assertEqual(s['target'], 24040.0)

    def test_glued_multi_target_takes_first_value_not_concatenation(self):
        # Channel-agnostic _f() bug: a comma-separated multi-target list
        # with no space after the comma ("TARGET 165,190+") was being read
        # as one Indian-grouped number (165190.0) instead of two separate
        # targets. First value should win, per this file's existing
        # "first/lower value is representative" convention.
        from traderacker.signals import parse_message
        text = 'NIFTY 23900CE \n\nBUY above 150-52\n\nSL. 130 \n\nTARGET 165,190+ '
        sigs = parse_message(text, style='auto')
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['target'], 165.0)

    def test_f_still_reads_genuine_grouped_price(self):
        # A real Indian/Western thousands-grouped price must still parse
        # correctly -- only an equal-length-groups glued list gets split.
        from traderacker.signals import _f
        self.assertEqual(_f('23,650'), 23650.0)
        self.assertEqual(_f('1,23,456'), 123456.0)
        self.assertEqual(_f('9,000'), 9000.0)

    def test_hari_cash_entry_band_recovers_ticker_from_prior_line(self):
        # LIVELONG HARI's "BUY ABV <price>-<price>" / "BUY RANGE
        # <price>-<price>" shape must recover the real ticker from the
        # preceding line instead of reading "ABV"/"RANGE" as the ticker.
        from traderacker.signals import parse_message
        text = 'EQUITY INTRADAY\n\nWOCKPHARMA \n\nBUY RANGE 2200-05\n\nSL 2150\n\nTarget 2220,2250+'
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'WOCKPHARMA')
        self.assertEqual(s['entry'], 2200.0)
        self.assertEqual(s['stop_loss'], 2150.0)
        self.assertEqual(s['target'], 2220.0)

    def test_hari_entry_band_shorthand_does_not_steal_real_target(self):
        # "262-65" is an entry BAND shorthand (262 to 265), not an
        # entry-target pair -- the real target comes from the TARGET line.
        from traderacker.signals import parse_message
        text = 'CRUDEOIL 8450 PE\n\nBUY\xa0 abv 262-65\n\nSL 240\n\nTARGET 280,300 +'
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['entry'], 262.0)
        self.assertEqual(s['target'], 280.0)

    def test_hari_trigger_word_not_anchored_to_line_start_is_ignored(self):
        # An ordinary sentence containing "buy above <price>" after some
        # OTHER word on the same line must not misread that word as the
        # ticker (Platinum Research's "Dnt buy above 7", not LIVELONG
        # HARI's own dedicated-line shape).
        from traderacker.signals import parse_message
        text = 'Unlock BTST TRADE AND IF HITS SL get 2 RECOVERY TRADE\nDnt buy above 7\nNow at 7 - ADD NOW'
        sigs = parse_message(text, style='mixed')
        self.assertEqual([s['trade'] for s in sigs], [])

    def test_usha_month_option_header_recovers_real_ticker(self):
        # Usha's Analysis's "<TICKER> <MONTH> <STRIKE> CE/PE" option header
        # must recover the real underlying, not the month word.
        from traderacker.signals import parse_message
        text = 'STOCK OPTIONS TRADE UPDATE\n\nBHARATFORG JUNE 1900 CE\n\n88 TO 124✅✅\n\nLOT SIZE 500'
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'BHARATFORG 1900 CE')
        self.assertEqual(s['entry'], 88.0)

    def test_month_name_option_header_elsewhere_produces_no_phantom(self):
        # Channel-agnostic safety net: even without the dedicated 'mixed'
        # recovery step, a full month name between ticker and strike must
        # never create a phantom "<MONTH> <STRIKE> CE" row for another
        # channel's style.
        from traderacker.signals import parse_message
        sigs = parse_message('SOMECO JUNE 4300 CE', style='auto')
        self.assertEqual(sigs, [])

    def test_usha_at_entry_with_target_anchor(self):
        # Usha's Analysis's live cash-equity call: "<TICKER> AT <price>"
        # followed a few lines later by a TARGET line.
        from traderacker.signals import parse_message
        text = 'SHORT TERM EQUITY\n\nQUADFUTURE AT 485\n\nTARGET 520,544+\n\nSTOP LOSS TO PREMIUM'
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'QUADFUTURE')
        self.assertEqual(s['entry'], 485.0)
        self.assertEqual(s['target'], 520.0)

    def test_usha_at_entry_ignores_lowercase_prose_elsewhere(self):
        # Case-sensitivity guard: ordinary lower/mixed-case "<word> at
        # <price>" prose in another channel must not be misread as this
        # channel's entry shape.
        from traderacker.signals import parse_message
        sigs = parse_message('Angel One Research bought 10 shares at 3970.00.\nTARGET update later', style='mixed')
        self.assertEqual(sigs, [])

    def test_sairam_buy_above_month_year_gap_not_truncated(self):
        # The expiry "<MONTH> <YEAR>" annotation between the strike and
        # "BUY ABOVE <price>" must not truncate the entry to a single
        # leading digit (the old 20-char window cut "1070" down to "1").
        from traderacker.signals import parse_message
        text = 'BANKNIFTY 55500 CALL SEP 2026\nBUY ABOVE 1070 LEVEL ONLY'
        sigs = parse_message(text, style='options')
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['entry'], 1070.0)

    def test_sairam_buy_above_colon_and_only_variants(self):
        from traderacker.signals import parse_message
        text1 = 'BANKNIFTY 55500 CALL SEP 2026\n\n\U0001F4CA BUY ABOVE : 1070\n\n\U0001F3AFTGT : 1130-1180-1230+++'
        sigs1 = parse_message(text1, style='options')
        self.assertEqual(sigs1[0]['entry'], 1070.0)
        self.assertEqual(sigs1[0]['target'], 1130.0)
        text2 = 'BANKNIFTY 56100 CALL SEP 2026\nBUY ABOVE ONLY 1060 LEVEL'
        sigs2 = parse_message(text2, style='options')
        self.assertEqual(sigs2[0]['entry'], 1060.0)

    def test_sl_below_not_misread_as_entry_trigger(self):
        # "SL BELOW <price>" is a stop-loss threshold, not an ABOVE/BELOW
        # entry trigger -- must not be picked up by the widened lookahead.
        from traderacker.signals import parse_message
        text = 'Option BUY CRUDE 7850CE BR 370-350 SL BELOW 280 TGT 450-480'
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['entry'], 370.0)
        self.assertNotEqual(sigs[0]['entry'], 280.0)

    def test_stockbox_oi_table_line_not_read_as_ticker(self):
        # Stockbox Trading's "OI DATA UPDATE" table: the trailing "OI"
        # word at the end of one line must not be read as the ticker for
        # the strike on the NEXT line.
        from traderacker.signals import parse_message
        text = ('⚡ NIFTY AT CRUCIAL SUPPORT & RESISTANCE ZONE\n\n'
                '\U0001F4CA OI DATA UPDATE:\n23,500 PE – 1.14 Cr OI\n24,000 CE – 1.20 Cr OI')
        sigs = parse_message(text, style='mixed')
        self.assertEqual([s['trade'] for s in sigs if s['trade'].startswith('OI')], [])

    def test_theta_gainers_and_equiideas_style_promo(self):
        # Sanity check on the batch5 style_notes migration: pure
        # commentary/promo channels should short-circuit to no signal.
        from traderacker.signals import parse_message
        text = 'PCR is 0.95 around ATM and 0.8 overall- neutral to bullish'
        self.assertEqual(parse_message(text, style='promo'), [])

    def test_usha_around_entry_recovers_ticker_from_prior_line(self):
        # Usha's Analysis's other entry keyword: "<TICKER>\n\nBUY AROUND
        # <price>" must recover QUESS, not the filler word "AROUND".
        from traderacker.signals import parse_message
        text = 'SHORT TERM EQUITY\n\nQUESS\n\nBUY AROUND 347\n\nTARGET 380,410+\n\nSTOP LOSS TO PREMIUM'
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s['trade'], 'QUESS')
        self.assertEqual(s['entry'], 347.0)
        self.assertEqual(s['target'], 380.0)

    def test_usha_around_entry_strips_futures_month_suffix(self):
        # A futures header with a trailing "<MONTH> FUTURES" suffix must
        # still resolve to the bare underlying ticker.
        from traderacker.signals import parse_message
        text = 'SHORT TERM\n\nMPHASIS AUG FUTURES \n\nAROUND 2515\n\nTARGET 2550,2600+\n\nSTOP LOSS TO PREMIUM'
        sigs = parse_message(text, style='mixed')
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0]['trade'], 'MPHASIS')
        self.assertEqual(sigs[0]['entry'], 2515.0)

    def test_subscription_combo_pack_promo_not_a_phantom_trade(self):
        # Usha's Analysis's subscription-pricing spam ("BUY 1 MONTH GET 2
        # FREE") must not be misread as a real "BUY <SYM>" trade order,
        # even though the message contains the literal word "BUY".
        from traderacker.signals import parse_message
        text = ("SPECIAL OFFER'S FOR STOCK OPTIONS SERVICES\n\n"
                "BUY 1 MONTH GET 2 FREE\n\nBUY 3 MONTHS GET 4 FREE\n\n\n"
                "JOINING LINK\nhttps://cosmofeed.com/vig/xyz")
        self.assertEqual(parse_message(text, style='mixed'), [])

    def test_subscription_combo_pack_offers_plural_and_pack_word(self):
        from traderacker.signals import parse_message
        text = ('SPECIAL COMBO OFFERS\n\nALL IN ONE COMBO PACK\n\n'
                'BUY 1 MONTH GET 2 MONTHS FREE\n(PRICE 4999)\n\n'
                'BUY 3 MONTHS GET 4 MONTHS FREE\n(PRICE 6999)\n\n\n'
                'JOINING LINK\nhttps://cosmofeed.com/vig/xyz')
        self.assertEqual(parse_message(text, style='mixed'), [])


class MarketServiceTests(TestCase):
    """Symbol→ticker mapping and provider fallback (no real network)."""

    def test_ticker_mapping(self):
        from traderacker import market
        self.assertEqual(market.yahoo_ticker('RELIANCE', 'stock'), 'RELIANCE.NS')
        self.assertEqual(market.yahoo_ticker('NIFTY', 'index'), '^NSEI')
        self.assertEqual(market.yahoo_ticker('BANKNIFTY', 'option'), '^NSEBANK')
        self.assertEqual(market.yahoo_ticker('BTC', 'crypto'), 'BTC-USD')
        self.assertEqual(market.yahoo_ticker('GOLD', 'metal'), 'GC=F')
        self.assertEqual(market.yahoo_ticker('USDINR', 'forex'), 'USDINR=X')
        self.assertEqual(market.yahoo_ticker('NIFTY 24000 CE', 'option'), '^NSEI')

    def test_get_price_yahoo_ok_and_fallback(self):
        from traderacker import market
        orig = market._curl_json
        try:
            market._curl_json = lambda url: {'chart': {'result': [{'meta': {'regularMarketPrice': 1257.5}}]}}
            self.assertEqual(market.get_price('RELIANCE', 'stock'), (1257.5, 'yahoo'))
            market._curl_json = lambda url: {'chart': {'result': None, 'error': {}}}
            self.assertEqual(market.get_price('NOPE', 'stock'), (None, None))
        finally:
            market._curl_json = orig

    def test_get_price_never_raises_on_garbage(self):
        from traderacker import market
        orig = market._curl_json
        try:
            market._curl_json = lambda url: {'unexpected': 'shape'}
            self.assertEqual(market.get_price('X', 'stock'), (None, None))
        finally:
            market._curl_json = orig


class PaperEngineTests(TestCase):
    """Paper-trade open/mark/close engine (fat model)."""

    def setUp(self):
        self.user = User.objects.create_user('pap', password='pw12345!')
        self.pref = UserPreference.for_user(self.user)

    def test_open_uses_pref_capital_and_stops(self):
        pt = PaperTrade.open_for_user(self.user, 'TATAMOTORS', 'stock', 'BUY', 100.0,
                                      source='yahoo')
        self.assertEqual(pt.notional_inr, 10000)
        self.assertEqual(pt.entry_price, 100.0)
        self.assertEqual(pt.stop_loss_pct, 20.0)
        self.assertEqual(pt.price_source, 'yahoo')

    def test_stop_loss_closes_buy(self):
        pt = PaperTrade.open_for_user(self.user, 'X', 'stock', 'BUY', 100.0)
        self.assertTrue(pt.mark(78.0))
        pt.refresh_from_db()
        self.assertEqual(pt.status, 'Closed')
        self.assertAlmostEqual(pt.realized_pct, -22.0)
        self.assertAlmostEqual(pt.realized_inr, -2200.0)

    def test_trailing_stop_locks_profit(self):
        pt = PaperTrade.open_for_user(self.user, 'X', 'stock', 'BUY', 100.0)
        self.assertFalse(pt.mark(130.0))
        self.assertEqual(pt.highest_price, 130.0)
        self.assertTrue(pt.mark(103.0))
        pt.refresh_from_db()
        self.assertEqual(pt.status, 'Closed')
        self.assertGreater(pt.realized_pct, 0)

    def test_profit_target_closes_before_trailing(self):
        # A jump straight past the 50% profit target closes immediately,
        # even though the trailing stop (20%, default) hasn't been touched
        # yet (price is still rising, no pullback from peak).
        pt = PaperTrade.open_for_user(self.user, 'X', 'stock', 'BUY', 100.0)
        self.assertEqual(pt.profit_target_pct, 50.0)
        self.assertTrue(pt.mark(151.0))
        pt.refresh_from_db()
        self.assertEqual(pt.status, 'Closed')
        self.assertIn('profit-target', pt.notes)
        self.assertGreaterEqual(pt.realized_pct, 50.0)

    def test_stop_loss_takes_priority_over_profit_target(self):
        # A custom pref combo where the two thresholds could both look
        # "reached" on the same mark must still resolve loss-cap first.
        pt = PaperTrade.open_for_user(self.user, 'X', 'stock', 'BUY', 100.0)
        pt.profit_target_pct = 5.0
        pt.stop_loss_pct = 5.0
        pt.save(update_fields=['profit_target_pct', 'stop_loss_pct'])
        self.assertTrue(pt.mark(94.0))
        pt.refresh_from_db()
        self.assertIn('stop-loss', pt.notes)

    def test_open_uses_pref_profit_target(self):
        self.pref.profit_target_pct = 35.0
        self.pref.save(update_fields=['profit_target_pct'])
        pt = PaperTrade.open_for_user(self.user, 'X', 'stock', 'BUY', 100.0)
        self.assertEqual(pt.profit_target_pct, 35.0)

    def test_max_hold_force_closes_no_matter_what(self):
        # 61 days in, still comfortably inside every price-based threshold
        # (only +2%), but the hard 60-day deadline closes it anyway.
        import datetime as dt
        from django.utils import timezone as tz
        pt = PaperTrade.open_for_user(self.user, 'X', 'stock', 'BUY', 100.0)
        self.assertEqual(pt.max_hold_days, 60)
        future = pt.opened_at + dt.timedelta(days=61)
        self.assertTrue(pt.mark(102.0, now=future))
        pt.refresh_from_db()
        self.assertEqual(pt.status, 'Closed')
        self.assertIn('max-hold', pt.notes)
        self.assertAlmostEqual(pt.realized_pct, 2.0)

    def test_max_hold_force_closes_even_with_no_live_quote(self):
        # "no matter what": a delisted/illiquid symbol with no fresh quote
        # must still get force-closed past the deadline, using the last
        # known price rather than sitting open forever.
        import datetime as dt
        pt = PaperTrade.open_for_user(self.user, 'X', 'stock', 'BUY', 100.0)
        future = pt.opened_at + dt.timedelta(days=90)
        self.assertTrue(pt.mark(None, now=future))
        pt.refresh_from_db()
        self.assertEqual(pt.status, 'Closed')
        self.assertIn('max-hold', pt.notes)
        self.assertEqual(pt.exit_price, 100.0)   # fell back to entry_price

    def test_no_action_with_no_quote_before_deadline(self):
        pt = PaperTrade.open_for_user(self.user, 'X', 'stock', 'BUY', 100.0)
        self.assertFalse(pt.mark(None))
        pt.refresh_from_db()
        self.assertEqual(pt.status, 'Open')

    def test_open_uses_pref_max_hold_days(self):
        self.pref.max_hold_days = 30
        self.pref.save(update_fields=['max_hold_days'])
        pt = PaperTrade.open_for_user(self.user, 'X', 'stock', 'BUY', 100.0)
        self.assertEqual(pt.max_hold_days, 30)

    def test_sell_side_profits_when_price_falls(self):
        pt = PaperTrade.open_for_user(self.user, 'X', 'stock', 'SELL', 100.0)
        self.assertFalse(pt.mark(90.0))
        self.assertAlmostEqual(pt.unrealized_pct(90.0), 10.0)

    def test_accuracy_set_on_close(self):
        pt = PaperTrade.open_for_user(self.user, 'X', 'stock', 'BUY', 100.0,
                                      consumer_claimed_pct=25.0)
        pt.mark(78.0)
        pt.refresh_from_db()
        self.assertEqual(pt.accuracy, 0.0)

    def test_channel_accuracy_aggregation(self):
        ch = Channel.objects.create(peer='-9', name='Ch', short='Ch')
        t = Trade.objects.create(channel=ch, trade='X', entry=100, realized=25,
                                 status='Closed', asset_class='stock', source_mid=1)
        pt = PaperTrade.open_for_user(self.user, 'X', 'stock', 'BUY', 100.0,
                                      source_trade=t, consumer_claimed_pct=25.0)
        pt.close(120.0)   # market +20%, consumer claimed +25% → direction agrees
        rows = PaperTrade.objects.channel_accuracy(user=self.user)
        self.assertEqual(rows[0]['channel'], ch.id)
        self.assertEqual(rows[0]['hit_rate'], 100.0)

    def test_side_for(self):
        from traderacker.management.commands.paper_autotrade import side_for
        self.assertEqual(side_for('CALL (up)'), 'BUY')
        self.assertEqual(side_for('BUY'), 'BUY')
        self.assertEqual(side_for('PUT (down)'), 'SELL')
        self.assertEqual(side_for('SELL'), 'SELL')


class PicksApiTests(TestCase):
    """Sector filtering + consensus picks endpoints."""

    def setUp(self):
        self.user = User.objects.create_user('tester2', password='pw12345!')
        self.client.force_login(self.user)
        self.a = Channel.objects.create(peer='-2001', name='A', short='A')
        self.b = Channel.objects.create(peer='-2002', name='B', short='B')
        d = dt.date(2026, 9, 10)
        Trade.objects.create(channel=self.a, date=d, trade='NIFTY 24000 CE',
                             direction='CALL (up)', entry=100, realized=50,
                             status='Closed', asset_class='option')
        Trade.objects.create(channel=self.a, date=d, trade='TATAMOTORS',
                             direction='BUY', entry=500, realized=20,
                             status='Closed', asset_class='stock')
        Trade.objects.create(channel=self.b, date=d, trade='ABFRL',
                             direction='BUY', entry=100, asset_class='stock')
        Trade.objects.create(channel=self.b, date=d, trade='ABFRL',
                             direction='SELL', entry=99, asset_class='stock')

    def test_sectors_filter_scopes_stats(self):
        opt = self.client.get('/api/tracker/stats/?sectors=option').json()
        both = self.client.get('/api/tracker/stats/').json()
        self.assertEqual(opt['realized'], 50.0)
        self.assertEqual(both['realized'], 70.0)

    def test_sectors_invalid_returns_400(self):
        self.assertEqual(self.client.get('/api/tracker/stats/?sectors=bogus').status_code, 400)

    def test_picks_endpoint(self):
        rows = self.client.get('/api/tracker/picks/').json()['results']
        ab = next(r for r in rows if r['symbol'] == 'ABFRL')
        self.assertEqual(ab['buy'], 1)
        self.assertEqual(ab['sell'], 1)
        self.assertEqual(ab['net'], 0)
        # weighted fields are present alongside the raw counts
        self.assertIn('weighted_buy', ab)
        self.assertIn('weighted_sell', ab)
        self.assertIn('diverges', ab)


class ConfidenceScoringTests(TestCase):
    """Wilson-lower-bound confidence scoring & trust tiers (audit item 2)."""

    def test_wilson_lower_bound_penalizes_small_samples(self):
        # 100% on 3 trades should score lower than 90% on 56 trades
        small_sample = wilson_lower_bound(3, 3)
        large_sample = wilson_lower_bound(50, 56)
        self.assertLess(small_sample, large_sample)

    def test_wilson_lower_bound_none_without_sample(self):
        self.assertIsNone(wilson_lower_bound(0, 0))

    def test_trust_tier_avoid_for_poor_large_sample(self):
        self.assertEqual(trust_tier(20.0, 20), 'avoid')

    def test_trust_tier_building_for_hot_streak(self):
        # a channel with 100% on 3 trades is 'building', not 'top'
        self.assertEqual(trust_tier(100.0, 3), 'building')

    def test_trust_tier_top_needs_both_rate_and_sample(self):
        self.assertEqual(trust_tier(90.0, 56), 'top')
        self.assertEqual(trust_tier(90.0, 3), 'building')

    def test_breakdown_exposes_confidence_score_and_tier_label(self):
        ch = Channel.objects.create(peer='-3001', name='C', short='C')
        for i in range(10):
            Trade.objects.create(channel=ch, trade=f'T{i}', entry=100,
                                 realized=10, status='Closed')
        rows = Trade.objects.breakdown()
        row = rows[0]
        self.assertIn('confidence_score', row)
        self.assertIn('tier_label', row)
        self.assertEqual(row['tier'], 'top')
        self.assertEqual(row['tier_label'], 'Top tier')


class TodaysCallsApiTests(TestCase):
    """Live feed endpoint (audit item 3)."""

    def setUp(self):
        self.user = User.objects.create_user('tester3', password='pw12345!')
        self.client.force_login(self.user)
        self.ch = Channel.objects.create(peer='-4001', name='Recent', short='R')
        Trade.objects.create(channel=self.ch, trade='FRESH', entry=100,
                             direction='BUY', status='Open',
                             posted_at=timezone.now())
        Trade.objects.create(channel=self.ch, trade='STALE', entry=100,
                             direction='BUY', status='Open',
                             posted_at=timezone.now() - dt.timedelta(days=5))

    def test_only_recent_calls_returned(self):
        r = self.client.get('/api/tracker/calls/?hours=24')
        self.assertEqual(r.status_code, 200)
        rows = r.json()['results']
        trades = [row['trade'] for row in rows]
        self.assertIn('FRESH', trades)
        self.assertNotIn('STALE', trades)
        self.assertIn('channel_tier', rows[0])
        self.assertIn('channel_confidence_score', rows[0])

    def test_wider_window_includes_stale(self):
        r = self.client.get('/api/tracker/calls/?hours=240')
        trades = [row['trade'] for row in r.json()['results']]
        self.assertIn('STALE', trades)

    def test_invalid_hours_returns_400(self):
        r = self.client.get('/api/tracker/calls/?hours=notanumber')
        self.assertEqual(r.status_code, 400)


class WatchlistApiTests(TestCase):
    """Per-user followed-channels CRUD (audit item 4)."""

    def setUp(self):
        self.user = User.objects.create_user('tester4', password='pw12345!')
        self.client.force_login(self.user)
        self.ch = Channel.objects.create(peer='-5001', name='Fav', short='F')

    def test_follow_list_unfollow(self):
        r = self.client.post('/api/tracker/watchlist/', {'channel': self.ch.id})
        self.assertEqual(r.status_code, 201)
        r = self.client.get('/api/tracker/watchlist/')
        rows = r.json()['results'] if 'results' in r.json() else r.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['channel'], self.ch.id)
        wl_id = rows[0]['id']
        r = self.client.delete(f'/api/tracker/watchlist/{wl_id}/')
        self.assertEqual(r.status_code, 204)
        self.assertEqual(Watchlist.objects.count(), 0)

    def test_duplicate_follow_is_idempotent(self):
        self.client.post('/api/tracker/watchlist/', {'channel': self.ch.id})
        r = self.client.post('/api/tracker/watchlist/', {'channel': self.ch.id})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Watchlist.objects.count(), 1)

    def test_watchlist_is_per_user(self):
        other = User.objects.create_user('other4', password='pw12345!')
        Watchlist.objects.create(user=other, channel=self.ch)
        r = self.client.get('/api/tracker/watchlist/')
        rows = r.json()['results'] if 'results' in r.json() else r.json()
        self.assertEqual(len(rows), 0)


class TradesExportApiTests(TestCase):
    """CSV export (audit item 5)."""

    def setUp(self):
        self.user = User.objects.create_user('tester5', password='pw12345!')
        self.client.force_login(self.user)
        self.ch = Channel.objects.create(peer='-6001', name='Exp', short='E')
        Trade.objects.create(channel=self.ch, trade='X', entry=100,
                             realized=10, status='Closed')

    def test_export_returns_csv(self):
        r = self.client.get('/api/tracker/trades/export/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'text/csv')
        body = r.content.decode()
        self.assertIn('channel', body.splitlines()[0])
        self.assertIn('X', body)

    def test_export_scoped_to_channel(self):
        other = Channel.objects.create(peer='-6002', name='Other', short='O')
        Trade.objects.create(channel=other, trade='Y', entry=50, status='Open')
        r = self.client.get(f'/api/tracker/trades/export/?channel={self.ch.id}')
        body = r.content.decode()
        self.assertIn('X', body)
        self.assertNotIn('Y', body)
