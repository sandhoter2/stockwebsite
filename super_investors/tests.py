from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from .management.commands.import_13f_filings import _parse_infotable
from .models import Holding, SuperInvestor


class SuperInvestorModelTests(TestCase):
    def setUp(self):
        self.investor = SuperInvestor.objects.create(
            name='Michael Burry', fund_name='Scion Asset Management LLC',
            cik='0001649339')

    def test_short_label(self):
        self.assertEqual(self.investor.short_label, 'Burry (Scion)')

    def test_new_position_change_summary(self):
        h = Holding.objects.create(
            investor=self.investor, cusip='037833100', issuer_name='APPLE INC',
            ticker='AAPL', shares=100000, market_value=20000000,
            filing_quarter=date(2025, 6, 30), filed_date=date(2025, 8, 14))
        self.assertEqual(h.change_kind, 'new')
        self.assertIn('opened new position in AAPL', h.change_summary_line)

    def test_increased_position_change_summary(self):
        Holding.objects.create(
            investor=self.investor, cusip='037833100', issuer_name='APPLE INC',
            ticker='AAPL', shares=100000, market_value=20000000,
            filing_quarter=date(2025, 3, 31), filed_date=date(2025, 5, 15))
        h2 = Holding.objects.create(
            investor=self.investor, cusip='037833100', issuer_name='APPLE INC',
            ticker='AAPL', shares=150000, market_value=30000000,
            filing_quarter=date(2025, 6, 30), filed_date=date(2025, 8, 14))
        self.assertEqual(h2.change_kind, 'increased')
        self.assertEqual(h2.change_pct, 50.0)
        self.assertIn('increased AAPL position by 50.0%', h2.change_summary_line)

    def test_decreased_position_change_summary(self):
        Holding.objects.create(
            investor=self.investor, cusip='037833100', issuer_name='APPLE INC',
            ticker='AAPL', shares=100000, market_value=20000000,
            filing_quarter=date(2025, 3, 31), filed_date=date(2025, 5, 15))
        h2 = Holding.objects.create(
            investor=self.investor, cusip='037833100', issuer_name='APPLE INC',
            ticker='AAPL', shares=50000, market_value=10000000,
            filing_quarter=date(2025, 6, 30), filed_date=date(2025, 8, 14))
        self.assertEqual(h2.change_kind, 'decreased')
        self.assertEqual(h2.change_pct, -50.0)
        self.assertIn('decreased AAPL position by 50.0%', h2.change_summary_line)

    def test_closed_position_change_summary(self):
        Holding.objects.create(
            investor=self.investor, cusip='037833100', issuer_name='APPLE INC',
            ticker='AAPL', shares=100000, market_value=20000000,
            filing_quarter=date(2025, 3, 31), filed_date=date(2025, 5, 15))
        h2 = Holding.objects.create(
            investor=self.investor, cusip='037833100', issuer_name='APPLE INC',
            ticker='AAPL', shares=0, market_value=0,
            filing_quarter=date(2025, 6, 30), filed_date=date(2025, 8, 14))
        self.assertEqual(h2.change_kind, 'closed')
        self.assertIn('closed position in AAPL', h2.change_summary_line)
        self.assertEqual(h2.buy_or_sell, 'Sell')
        # 13F doesn't report a sale price, so profit is never fabricated
        # for a closed position -- None, not a guessed number.
        self.assertIsNone(h2.profit_estimate)

    def test_new_position_has_no_profit_estimate(self):
        h = Holding.objects.create(
            investor=self.investor, cusip='037833100', issuer_name='APPLE INC',
            ticker='AAPL', shares=100000, market_value=20000000,
            filing_quarter=date(2025, 6, 30), filed_date=date(2025, 8, 14))
        self.assertEqual(h.buy_or_sell, 'Buy')
        self.assertIsNone(h.profit_estimate)

    def test_uniqueness_constraint_upsert_key(self):
        Holding.objects.create(
            investor=self.investor, cusip='037833100', issuer_name='APPLE INC',
            shares=1, market_value=1, filing_quarter=date(2025, 6, 30),
            filed_date=date(2025, 8, 14))
        with self.assertRaises(Exception):
            Holding.objects.create(
                investor=self.investor, cusip='037833100', issuer_name='APPLE INC',
                shares=2, market_value=2, filing_quarter=date(2025, 6, 30),
                filed_date=date(2025, 8, 14))


class MovesQuerySetTests(TestCase):
    def setUp(self):
        self.investor = SuperInvestor.objects.create(
            name='Warren Buffett', fund_name='Berkshire Hathaway Inc',
            cik='0001067983')
        # Q1: opened AAPL; Q2: increased AAPL, opened MSFT; unaffected control
        Holding.objects.create(
            investor=self.investor, cusip='037833100', issuer_name='APPLE INC',
            ticker='AAPL', shares=100000, market_value=20000000,
            filing_quarter=date(2025, 3, 31), filed_date=date(2025, 5, 15))
        Holding.objects.create(
            investor=self.investor, cusip='037833100', issuer_name='APPLE INC',
            ticker='AAPL', shares=200000, market_value=40000000,
            filing_quarter=date(2025, 6, 30), filed_date=date(2025, 8, 14))
        Holding.objects.create(
            investor=self.investor, cusip='594918104', issuer_name='MICROSOFT CORP',
            ticker='MSFT', shares=50000, market_value=15000000,
            filing_quarter=date(2025, 6, 30), filed_date=date(2025, 8, 14))

    def test_moves_flags_new_and_increased(self):
        results = Holding.objects.moves(quarters=2)
        kinds = {(r['ticker'], r['change_kind']) for r in results}
        self.assertIn(('MSFT', 'new'), kinds)
        self.assertIn(('AAPL', 'increased'), kinds)

    def test_moves_new_positions_rank_first(self):
        results = Holding.objects.moves(quarters=2)
        # 'new' (rank 0) should come before 'increased' (rank 1)
        kind_ranks = {'new': 0, 'closed': 0, 'increased': 1, 'decreased': 1}
        ranks = [kind_ranks.get(r['change_kind'], 2) for r in results]
        self.assertEqual(ranks, sorted(ranks))

    def test_moves_filters_by_ticker(self):
        results = Holding.objects.moves(quarters=2, ticker='MSFT')
        self.assertTrue(all(r['ticker'] == 'MSFT' for r in results))
        self.assertTrue(len(results) >= 1)

    def test_moves_buy_sell_and_profit_estimate(self):
        results = Holding.objects.moves(quarters=2)
        by_ticker = {r['ticker']: r for r in results}
        # MSFT is a brand-new position: Buy, but no comparable prior quarter
        # so profit can't be estimated (not fabricated as 0).
        self.assertEqual(by_ticker['MSFT']['buy_or_sell'], 'Buy')
        self.assertIsNone(by_ticker['MSFT']['profit_estimate'])
        # AAPL doubled shares (100k->200k) at the same $200/share market
        # value implied both quarters ($20M/100k == $40M/200k): pure
        # share-count growth, no price movement, so the isolated
        # price-driven profit estimate is correctly $0 -- all the added
        # market value there is new capital, not gain.
        self.assertEqual(by_ticker['AAPL']['buy_or_sell'], 'Buy')
        self.assertEqual(by_ticker['AAPL']['profit_estimate'], 0.0)
        self.assertTrue(by_ticker['AAPL']['profit_is_estimated'])

    def test_investor_profile_aggregates(self):
        profile = Holding.objects.investor_profile(self.investor.id)
        self.assertEqual(profile['quarters_tracked'], 2)
        self.assertEqual(profile['positions_tracked'], 2)  # AAPL + MSFT
        # AAPL's first-ever quarter (Q1, no prior to diff against) and
        # MSFT (opened in Q2) both surface as 'new'; AAPL's Q2 row is the
        # separate 'increased' diff against its own Q1 -- moves() emits one
        # row per in-scope quarter, not one row per ticker.
        self.assertEqual(profile['moves_new'], 2)
        self.assertEqual(profile['moves_increased'], 1)
        self.assertEqual(profile['total_moves'], 3)
        self.assertEqual(len(profile['moves']), 3)
        self.assertIn('conviction_tier', profile)


class ParseInfoTableTests(TestCase):
    def test_parses_well_formed_infotable(self):
        xml = """<?xml version="1.0" ?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>037833100</cusip>
    <value>20000000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>100000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority>
      <Sole>100000</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>
</informationTable>"""
        rows = _parse_infotable(xml)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['cusip'], '037833100')
        self.assertEqual(rows[0]['shares'], 100000)
        self.assertEqual(rows[0]['value'], 20000000)

    def test_gracefully_handles_malformed_xml(self):
        self.assertEqual(_parse_infotable('<not><valid'), [])

    def test_gracefully_handles_missing_fields(self):
        xml = """<?xml version="1.0" ?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <titleOfClass>COM</titleOfClass>
  </infoTable>
</informationTable>"""
        self.assertEqual(_parse_infotable(xml), [])


class ApiEndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='x')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.investor = SuperInvestor.objects.create(
            name='Michael Burry', fund_name='Scion Asset Management LLC',
            cik='0001649339')
        Holding.objects.create(
            investor=self.investor, cusip='037833100', issuer_name='APPLE INC',
            ticker='AAPL', shares=100000, market_value=20000000,
            filing_quarter=date(2025, 6, 30), filed_date=date(2025, 8, 14))

    def test_moves_requires_auth(self):
        anon = APIClient()
        resp = anon.get('/api/super-investors/moves/')
        self.assertIn(resp.status_code, (401, 403))

    def test_moves_returns_action_oriented_rows(self):
        resp = self.client.get('/api/super-investors/moves/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('results', data)
        self.assertEqual(len(data['results']), 1)
        row = data['results'][0]
        self.assertEqual(row['change_kind'], 'new')
        self.assertIn('change_summary_line', row)
        self.assertIn('opened new position', row['change_summary_line'])

    def test_moves_bad_quarters_param(self):
        resp = self.client.get('/api/super-investors/moves/?quarters=notanumber')
        self.assertEqual(resp.status_code, 400)

    def test_investors_list(self):
        resp = self.client.get('/api/super-investors/investors/')
        self.assertEqual(resp.status_code, 200)
        names = [r['name'] for r in resp.json()['results']]
        self.assertIn('Michael Burry', names)

    def test_holdings_list_filter_by_investor(self):
        resp = self.client.get(f'/api/super-investors/holdings/?investor={self.investor.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['count'], 1)

    def test_investor_profile_endpoint(self):
        resp = self.client.get(f'/api/super-investors/investors/{self.investor.id}/profile/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['investor'], self.investor.id)
        self.assertEqual(data['moves_new'], 1)
        self.assertIn('moves', data)
        self.assertEqual(data['moves'][0]['filing_quarter'], '2025-06-30')

    def test_investor_profile_404_for_unknown_investor(self):
        resp = self.client.get('/api/super-investors/investors/999999/profile/')
        self.assertEqual(resp.status_code, 404)
