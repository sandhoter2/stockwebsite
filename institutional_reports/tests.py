import datetime as dt

from django.contrib.auth.models import User
from django.test import TestCase

from institutional_reports.management.commands.import_market_reports import (
    clean_text, guess_report_type, parse_date)
from institutional_reports.models import MarketReport


class MarketReportApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('tester', password='pw12345!')
        self.client.force_login(self.user)
        today = dt.date(2026, 9, 10)
        MarketReport.objects.create(
            firm=MarketReport.FIRM_BLACKROCK, title='Weekly take: rates and risk',
            published_date=today, report_type=MarketReport.TYPE_WEEKLY_COMMENTARY,
            short_summary='A short weekly take.',
            source_url='https://www.blackrock.com/insights/weekly-1')
        MarketReport.objects.create(
            firm=MarketReport.FIRM_JPMORGAN, title='2026 Year Ahead Outlook',
            published_date=today - dt.timedelta(days=200),
            report_type=MarketReport.TYPE_YEARLY_FORECAST,
            short_summary='A yearly forecast summary.',
            source_url='https://www.jpmorgan.com/insights/year-ahead')

    def test_requires_auth(self):
        self.client.logout()
        r = self.client.get('/api/institutional/reports/')
        self.assertIn(r.status_code, (401, 403))

    def test_lists_recent_first(self):
        d = self.client.get('/api/institutional/reports/').json()
        titles = [r['title'] for r in d['results']]
        self.assertEqual(titles, ['Weekly take: rates and risk', '2026 Year Ahead Outlook'])

    def test_filter_by_firm(self):
        d = self.client.get('/api/institutional/reports/?firm=jpmorgan').json()
        self.assertEqual(d['count'], 1)
        self.assertEqual(d['results'][0]['firm'], 'jpmorgan')

    def test_filter_by_type(self):
        d = self.client.get('/api/institutional/reports/?type=weekly_commentary').json()
        self.assertEqual(d['count'], 1)
        self.assertEqual(d['results'][0]['report_type'], 'weekly_commentary')

    def test_filter_by_days_excludes_old(self):
        d = self.client.get('/api/institutional/reports/?days=30').json()
        self.assertEqual(d['count'], 1)
        self.assertEqual(d['results'][0]['title'], 'Weekly take: rates and risk')

    def test_unknown_firm_is_rejected(self):
        r = self.client.get('/api/institutional/reports/?firm=goldman')
        self.assertEqual(r.status_code, 400)

    def test_response_is_terse_not_full_text(self):
        """Each item exposes a short_summary + source_url pointer, no full-text field."""
        d = self.client.get('/api/institutional/reports/').json()
        row = d['results'][0]
        self.assertNotIn('full_text', row)
        self.assertNotIn('body', row)
        self.assertLess(len(row['short_summary']), 1000)
        self.assertTrue(row['source_url'].startswith('https://'))

    def test_source_url_is_dedupe_key(self):
        """Upsert semantics: re-creating with the same source_url should
        collide at the DB level (unique constraint), matching how the
        import command uses update_or_create keyed on source_url."""
        with self.assertRaises(Exception):
            MarketReport.objects.create(
                firm=MarketReport.FIRM_BLACKROCK, title='Duplicate',
                published_date=dt.date(2026, 9, 10),
                source_url='https://www.blackrock.com/insights/weekly-1')


class ImportHelpersTests(TestCase):
    """Smoke tests for the scraper's small, pure helper functions."""

    def test_parse_date_formats(self):
        self.assertEqual(parse_date('Sep 11, 2026'), dt.date(2026, 9, 11))
        self.assertEqual(parse_date('Jul 01, 2026'), dt.date(2026, 7, 1))
        self.assertIsNone(parse_date(''))
        self.assertIsNone(parse_date('not a date'))

    def test_clean_text_collapses_whitespace_and_truncates(self):
        self.assertEqual(clean_text('  a   b\n c '), 'a b c')
        long_text = 'word ' * 200
        out = clean_text(long_text, limit=50)
        self.assertLessEqual(len(out), 51)
        self.assertTrue(out.endswith('…'))

    def test_guess_report_type(self):
        self.assertEqual(guess_report_type('Weekly market commentary', 'x'),
                         MarketReport.TYPE_WEEKLY_COMMENTARY)
        self.assertEqual(guess_report_type('Q3 2026 outlook', 'x'),
                         MarketReport.TYPE_QUARTERLY_OUTLOOK)
        self.assertEqual(guess_report_type('2026 Year-ahead forecast', 'x'),
                         MarketReport.TYPE_YEARLY_FORECAST)
        self.assertEqual(guess_report_type('Why momentum can still work',
                                           MarketReport.TYPE_RESEARCH_NOTE),
                         MarketReport.TYPE_RESEARCH_NOTE)
