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
