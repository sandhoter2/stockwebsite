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

    def test_promo_messages_are_skipped(self):
        from traderacker.signals import parse_message, is_promo
        self.assertTrue(is_promo('Ganesh offer opens here, valid for first 50 slots only'))
        self.assertEqual(
            parse_message('Veegaland IPO final verdict — price band, lot size, '
                          'apply now https://youtu.be/x'), [])
        self.assertTrue(parse_message('Buy BHARTIHEXA above 1555 Target 1612'))


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
