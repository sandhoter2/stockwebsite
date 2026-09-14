import datetime as dt

from django.contrib.auth.models import User
from django.test import TestCase

from congress_trades.models import CongressTrade, format_amount


def _make(**kw):
    defaults = dict(
        politician_name='Nancy Pelosi', party='D', chamber='House', state='CA',
        ticker='NVDA', asset_description='NVIDIA Corporation',
        transaction_type='buy', amount_min=1_000_001, amount_max=5_000_000,
        transaction_date=dt.date(2026, 7, 28), disclosure_date=dt.date(2026, 8, 15),
        filing_url='https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/1.pdf',
        source_doc_id='1',
    )
    defaults.update(kw)
    return CongressTrade.objects.create(**defaults)


class FormatAmountTests(TestCase):
    def test_millions(self):
        self.assertEqual(format_amount(5_000_000), '$5M')
        self.assertEqual(format_amount(1_500_000), '$1.5M')

    def test_thousands(self):
        self.assertEqual(format_amount(15_000), '$15K')

    def test_small(self):
        self.assertEqual(format_amount(500), '$500')

    def test_none(self):
        self.assertEqual(format_amount(None), '?')


class CongressTradeModelTests(TestCase):
    def test_summary_line_format(self):
        t = _make()
        self.assertEqual(
            t.summary_line,
            "Nancy Pelosi (D) bought NVDA $1M–$5M · "
            "disclosed 2026-08-15 (trade date 2026-07-28)",
        )

    def test_summary_line_unknown_party(self):
        t = _make(party='?')
        self.assertTrue(t.summary_line.startswith("Nancy Pelosi bought"))

    def test_unique_constraint_upsert(self):
        _make()
        # same natural key -> update_or_create should update, not duplicate
        obj, created = CongressTrade.objects.update_or_create(
            chamber='House', source_doc_id='1', ticker='NVDA',
            transaction_date=dt.date(2026, 7, 28), transaction_type='buy',
            amount_min=1_000_001, amount_max=5_000_000,
            defaults={'politician_name': 'Nancy Pelosi', 'party': 'D', 'state': 'CA',
                     'asset_description': 'NVIDIA Corporation',
                     'disclosure_date': dt.date(2026, 8, 16),
                     'filing_url': 'https://example.com/x.pdf'},
        )
        self.assertFalse(created)
        self.assertEqual(CongressTrade.objects.count(), 1)
        self.assertEqual(obj.disclosure_date, dt.date(2026, 8, 16))

    def test_notable_orders_by_amount_desc(self):
        _make(ticker='NVDA', amount_min=1_000_001, amount_max=5_000_000,
             source_doc_id='1', disclosure_date=dt.date(2026, 9, 1))
        _make(ticker='AAPL', amount_min=15_001, amount_max=50_000,
             source_doc_id='2', disclosure_date=dt.date(2026, 9, 1))
        rows = CongressTrade.objects.notable(days=60, limit=5)
        self.assertEqual(rows[0].ticker, 'NVDA')


class CongressTradeApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('tester', password='pw12345!')
        self.client.force_login(self.user)
        _make(ticker='NVDA', politician_name='Nancy Pelosi', party='D',
             amount_min=1_000_001, amount_max=5_000_000, source_doc_id='1',
             disclosure_date=dt.date.today())
        _make(ticker='TSLA', politician_name='Dan Crenshaw', party='R',
             amount_min=1_001, amount_max=15_000, source_doc_id='2',
             disclosure_date=dt.date.today())

    def test_requires_auth(self):
        self.client.logout()
        r = self.client.get('/api/congress/trades/')
        self.assertIn(r.status_code, (401, 403))

    def test_list_returns_summary_line(self):
        r = self.client.get('/api/congress/trades/')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['count'], 2)
        self.assertIn('summary_line', data['results'][0])

    def test_filter_by_politician(self):
        r = self.client.get('/api/congress/trades/?politician=Pelosi')
        self.assertEqual(r.json()['count'], 1)
        self.assertEqual(r.json()['results'][0]['ticker'], 'NVDA')

    def test_filter_by_party(self):
        r = self.client.get('/api/congress/trades/?party=R')
        self.assertEqual(r.json()['count'], 1)
        self.assertEqual(r.json()['results'][0]['ticker'], 'TSLA')

    def test_notable_endpoint(self):
        r = self.client.get('/api/congress/trades/notable/')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['results'][0]['ticker'], 'NVDA')

    def test_list_row_has_table_shape(self):
        """Table needs time/resource/stock/buy_or_sell/profit per row."""
        r = self.client.get('/api/congress/trades/')
        row = r.json()['results'][0]
        for key in ('time', 'resource', 'ticker', 'buy_or_sell', 'profit', 'profit_kind'):
            self.assertIn(key, row)
        self.assertEqual(row['time'], row['transaction_date'])


class ProfitEstimateTests(TestCase):
    """Use fake price functions (no network) to pin down the FIFO-matching
    and profit-estimate math deterministically."""

    def _fake_prices(self, price_by_date):
        def historical_fn(ticker, on_date):
            return price_by_date.get((ticker, on_date))

        def price_fn(ticker):
            return price_by_date.get((ticker, 'current')), 'fake'
        return price_fn, historical_fn

    def test_realized_profit_on_matched_buy_sell(self):
        buy = _make(ticker='NVDA', transaction_type='buy',
                    amount_min=1_000_001, amount_max=5_000_000,   # mid 3,000,000.5
                    transaction_date=dt.date(2026, 1, 1), source_doc_id='b1')
        sell = _make(ticker='NVDA', transaction_type='sell',
                     amount_min=1_000_001, amount_max=5_000_000,
                     transaction_date=dt.date(2026, 2, 1), source_doc_id='s1')
        price_fn, hist_fn = self._fake_prices({
            ('NVDA', dt.date(2026, 1, 1)): 100.0,
            ('NVDA', dt.date(2026, 2, 1)): 110.0,   # +10%
        })
        n = CongressTrade.objects.compute_profit_estimates(price_fn=price_fn, historical_fn=hist_fn)
        self.assertEqual(n, 2)
        buy.refresh_from_db(); sell.refresh_from_db()
        self.assertEqual(buy.profit_kind, 'realized')
        self.assertEqual(sell.profit_kind, 'realized')
        self.assertAlmostEqual(buy.realized_profit, 300_000.05, places=2)
        self.assertEqual(buy.realized_profit, sell.realized_profit)
        self.assertEqual(buy.matched_trade_id, sell.id)
        self.assertIsNone(buy.unrealized_profit)

    def test_unrealized_profit_on_open_buy(self):
        buy = _make(ticker='AAPL', transaction_type='buy',
                    amount_min=15_001, amount_max=50_000,   # mid 32,500.5
                    transaction_date=dt.date(2026, 1, 1), source_doc_id='b2')
        price_fn, hist_fn = self._fake_prices({
            ('AAPL', dt.date(2026, 1, 1)): 200.0,
            ('AAPL', 'current'): 180.0,   # -10%
        })
        CongressTrade.objects.compute_profit_estimates(price_fn=price_fn, historical_fn=hist_fn)
        buy.refresh_from_db()
        self.assertEqual(buy.profit_kind, 'unrealized')
        self.assertAlmostEqual(buy.unrealized_profit, -3250.05, places=2)
        self.assertIsNone(buy.realized_profit)

    def test_sell_without_matching_buy_left_unpriced(self):
        sell = _make(ticker='MSFT', transaction_type='sell', source_doc_id='s3')
        price_fn, hist_fn = self._fake_prices({})
        CongressTrade.objects.compute_profit_estimates(price_fn=price_fn, historical_fn=hist_fn)
        sell.refresh_from_db()
        self.assertEqual(sell.profit_kind, '')
        self.assertIsNone(sell.profit)

    def test_fifo_matches_oldest_buy_first(self):
        buy1 = _make(ticker='TSLA', transaction_type='buy', amount_min=1_001, amount_max=15_000,
                     transaction_date=dt.date(2026, 1, 1), source_doc_id='fb1')
        _make(ticker='TSLA', transaction_type='buy', amount_min=1_001, amount_max=15_000,
             transaction_date=dt.date(2026, 1, 10), source_doc_id='fb2')
        sell = _make(ticker='TSLA', transaction_type='sell', amount_min=1_001, amount_max=15_000,
                     transaction_date=dt.date(2026, 2, 1), source_doc_id='fs1')
        price_fn, hist_fn = self._fake_prices({
            ('TSLA', dt.date(2026, 1, 1)): 50.0,
            ('TSLA', dt.date(2026, 1, 10)): 60.0,
            ('TSLA', dt.date(2026, 2, 1)): 55.0,
        })
        CongressTrade.objects.compute_profit_estimates(price_fn=price_fn, historical_fn=hist_fn)
        sell.refresh_from_db()
        self.assertEqual(sell.matched_trade_id, buy1.id)   # FIFO: oldest buy closed first

    def test_exchange_rows_skipped(self):
        ex = _make(ticker='IBM', transaction_type='exchange', source_doc_id='ex1')
        price_fn, hist_fn = self._fake_prices({})
        CongressTrade.objects.compute_profit_estimates(price_fn=price_fn, historical_fn=hist_fn)
        ex.refresh_from_db()
        self.assertEqual(ex.profit_kind, '')


class PoliticianBreakdownTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('tester2', password='pw12345!')
        self.client.force_login(self.user)
        self.buy = _make(politician_name='Nancy Pelosi', party='D', ticker='NVDA',
                         transaction_type='buy', amount_min=1_000_001, amount_max=5_000_000,
                         transaction_date=dt.date(2026, 1, 1), source_doc_id='pb1')
        self.sell = _make(politician_name='Nancy Pelosi', party='D', ticker='NVDA',
                          transaction_type='sell', amount_min=1_000_001, amount_max=5_000_000,
                          transaction_date=dt.date(2026, 2, 1), source_doc_id='ps1')

        def price_fn(ticker):
            return None, None

        def hist_fn(ticker, on_date):
            return {dt.date(2026, 1, 1): 100.0, dt.date(2026, 2, 1): 120.0}.get(on_date)
        CongressTrade.objects.compute_profit_estimates(price_fn=price_fn, historical_fn=hist_fn)

    def test_politician_breakdown_win_rate_and_tier(self):
        rows = CongressTrade.objects.politician_breakdown()
        row = next(r for r in rows if r['politician_name'] == 'Nancy Pelosi')
        self.assertEqual(row['closed'], 1)
        self.assertEqual(row['wins'], 1)
        self.assertEqual(row['win_rate'], 100.0)
        self.assertGreater(row['realized_profit'], 0)

    def test_politicians_endpoint(self):
        r = self.client.get('/api/congress/trades/politicians/')
        self.assertEqual(r.status_code, 200)
        names = [row['politician_name'] for row in r.json()['results']]
        self.assertIn('Nancy Pelosi', names)

    def test_politician_profile_endpoint(self):
        r = self.client.get('/api/congress/trades/politician-profile/?politician=Nancy Pelosi')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['profile']['politician_name'], 'Nancy Pelosi')
        self.assertEqual(len(data['trades']), 2)

    def test_politician_profile_requires_param(self):
        r = self.client.get('/api/congress/trades/politician-profile/')
        self.assertEqual(r.status_code, 400)

    def test_politician_profile_unknown_politician(self):
        r = self.client.get('/api/congress/trades/politician-profile/?politician=Nobody')
        self.assertEqual(r.status_code, 404)
