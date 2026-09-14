import json
import os
from datetime import timezone as dt_timezone
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from market_news.management.commands.import_market_news import (
    build_headline_line, condense_summary, extract_news_items, parse_time_published,
)
from market_news.models import NewsItem

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), 'fixtures', 'alphavantage_news_sentiment_sample.json')

# A small, hand-shaped payload mirroring Alpha Vantage's documented
# NEWS_SENTIMENT response (https://www.alphavantage.co/documentation/#news-sentiment),
# used for precise assertions on the parsing/formatting pipeline.
SAMPLE_PAYLOAD = {
    'items': '2',
    'sentiment_score_definition': 'x <= -0.35: Bearish; ...',
    'relevance_score_definition': '0 < x <= 1, with a higher score indicating higher relevance.',
    'feed': [
        {
            'title': 'AMD to Acquire Taalas in Push Into Custom AI Chips',
            'url': 'https://example.com/amd-taalas',
            'time_published': '20260910T093000',
            'authors': ['Jane Reporter'],
            'summary': (
                'Advanced Micro Devices announced it will acquire chip startup Taalas '
                'for an undisclosed sum. The deal strengthens AMD\'s laptop and edge-AI '
                'chip lineup as it competes more directly with Nvidia and Intel in '
                'custom silicon.'
            ),
            'banner_image': '',
            'source': 'Example Wire',
            'category_within_source': 'General',
            'source_domain': 'example.com',
            'topics': [{'topic': 'technology', 'relevance_score': '0.9'}],
            'overall_sentiment_score': 0.31,
            'overall_sentiment_label': 'Somewhat-Bullish',
            'ticker_sentiment': [
                {
                    'ticker': 'AMD',
                    'relevance_score': '0.87',
                    'ticker_sentiment_score': '0.41',
                    'ticker_sentiment_label': 'Bullish',
                },
                {
                    # below the default relevance threshold -> should be dropped
                    'ticker': 'INTC',
                    'relevance_score': '0.05',
                    'ticker_sentiment_score': '-0.10',
                    'ticker_sentiment_label': 'Neutral',
                },
            ],
        },
        {
            'title': 'Widget Corp Misses Revenue Estimates',
            'url': 'https://example.com/widget-corp-earnings',
            'time_published': '20260911T140000',
            'authors': [],
            'summary': 'Widget Corp reported quarterly revenue below analyst expectations.',
            'banner_image': '',
            'source': 'Example Wire',
            'category_within_source': 'Earnings',
            'source_domain': 'example.com',
            'topics': [{'topic': 'earnings', 'relevance_score': '0.8'}],
            'overall_sentiment_score': -0.4,
            'overall_sentiment_label': 'Bearish',
            'ticker_sentiment': [
                {
                    'ticker': 'WDGT',
                    'relevance_score': '0.75',
                    'ticker_sentiment_score': '-0.42',
                    'ticker_sentiment_label': 'Bearish',
                },
            ],
        },
        {
            # missing url/time_published -> whole article should be skipped
            'title': 'Malformed article',
            'url': '',
            'time_published': '',
            'summary': 'Should never appear.',
            'source': 'Example Wire',
            'ticker_sentiment': [
                {'ticker': 'ZZZZ', 'relevance_score': '0.99',
                 'ticker_sentiment_score': '0.0', 'ticker_sentiment_label': 'Neutral'},
            ],
        },
    ],
}


class ParsingHelpersTests(TestCase):
    def test_parse_time_published(self):
        dt = parse_time_published('20260913T132613')
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 9)
        self.assertEqual(dt.day, 13)
        self.assertEqual(dt.hour, 13)
        self.assertEqual(dt.tzinfo, dt_timezone.utc)

    def test_parse_time_published_garbage(self):
        self.assertIsNone(parse_time_published('not-a-date'))
        self.assertIsNone(parse_time_published(''))
        self.assertIsNone(parse_time_published(None))

    def test_condense_summary_two_sentences(self):
        out = condense_summary(
            'title',
            'AMD announced it will acquire Taalas. The deal strengthens its laptop '
            'chip lineup against Nvidia and Intel.')
        self.assertIn('→', out)
        self.assertTrue(out.startswith('AMD announced it will acquire Taalas'))

    def test_condense_summary_single_sentence_no_arrow(self):
        out = condense_summary('title', 'Just one sentence here.')
        self.assertNotIn('→', out)
        self.assertEqual(out, 'Just one sentence here')

    def test_condense_summary_falls_back_to_title(self):
        out = condense_summary('Fallback Title', '')
        self.assertEqual(out, 'Fallback Title')

    def test_build_headline_line_is_terse_and_prefixed(self):
        line = build_headline_line(
            'AMD', 'title',
            'AMD acquired Taalas. This strengthens AMD laptop chip sales against rivals.')
        self.assertTrue(line.startswith('AMD: '))
        self.assertLessEqual(len(line), 280)
        self.assertIn('→', line)


class ExtractNewsItemsTests(TestCase):
    def test_extracts_only_above_threshold_and_shapes_rows(self):
        rows = extract_news_items(SAMPLE_PAYLOAD, min_relevance=0.3)
        tickers = {r['ticker'] for r in rows}
        # INTC (relevance 0.05) filtered out; malformed article skipped entirely
        self.assertEqual(tickers, {'AMD', 'WDGT'})

        amd = next(r for r in rows if r['ticker'] == 'AMD')
        self.assertTrue(amd['headline_line'].startswith('AMD: '))
        self.assertIn('Taalas', amd['headline_line'])
        self.assertEqual(amd['sentiment'], 'bullish')
        self.assertAlmostEqual(amd['sentiment_score'], 0.41)
        self.assertAlmostEqual(amd['relevance_score'], 0.87)
        self.assertEqual(amd['source_url'], 'https://example.com/amd-taalas')
        self.assertEqual(amd['source'], 'Example Wire')
        self.assertIsNotNone(amd['published_at'])

        wdgt = next(r for r in rows if r['ticker'] == 'WDGT')
        self.assertEqual(wdgt['sentiment'], 'bearish')

    def test_relevance_threshold_is_applied(self):
        rows = extract_news_items(SAMPLE_PAYLOAD, min_relevance=0.8)
        tickers = {r['ticker'] for r in rows}
        self.assertEqual(tickers, {'AMD'})  # 0.87 clears 0.8; WDGT's 0.75 doesn't

    def test_handles_real_recorded_alphavantage_payload(self):
        """Smoke test against a real recorded NEWS_SENTIMENT response, proving
        the parser doesn't choke on live-shaped data and still curates it."""
        with open(FIXTURE_PATH) as f:
            payload = json.load(f)
        rows = extract_news_items(payload, min_relevance=0.3)
        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertGreaterEqual(row['relevance_score'], 0.3)
            self.assertTrue(row['headline_line'].startswith(row['ticker'] + ': '))
            self.assertIn(row['sentiment'], ('bullish', 'bearish', 'neutral'))


class ImportCommandTests(TestCase):
    def test_missing_api_key_raises_clear_error(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('ALPHAVANTAGE_API_KEY', None)
            with self.assertRaises(CommandError) as ctx:
                call_command('import_market_news')
        self.assertIn('ALPHAVANTAGE_API_KEY', str(ctx.exception))

    @patch('market_news.management.commands.import_market_news.requests.get')
    def test_upserts_rows_and_is_idempotent(self, mock_get):
        mock_get.return_value.json.return_value = SAMPLE_PAYLOAD
        mock_get.return_value.raise_for_status.return_value = None

        from django.core.management import call_command

        with patch.dict(os.environ, {'ALPHAVANTAGE_API_KEY': 'test-key'}):
            call_command('import_market_news')
            self.assertEqual(NewsItem.objects.count(), 2)

            # re-running is idempotent (upsert on source_url+ticker), not a dupe
            call_command('import_market_news')
            self.assertEqual(NewsItem.objects.count(), 2)

        amd = NewsItem.objects.get(ticker='AMD')
        self.assertEqual(amd.sentiment, 'bullish')
        self.assertTrue(amd.headline_line.startswith('AMD: '))


class NewsFeedViewTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User

        self.client = APIClient()
        self.user = User.objects.create_user('tester', password='pw12345!')
        self.client.force_authenticate(self.user)
        now = timezone.now()
        self.recent_high = NewsItem.objects.create(
            ticker='AMD', headline_line='AMD: acquired Taalas → strengthens chip lineup',
            sentiment='bullish', sentiment_score=0.4, relevance_score=0.9,
            source='Example Wire', source_url='https://example.com/1',
            published_at=now)
        self.recent_low_relevance = NewsItem.objects.create(
            ticker='AMD', headline_line='AMD: mentioned in passing',
            sentiment='neutral', sentiment_score=0.0, relevance_score=0.1,
            source='Example Wire', source_url='https://example.com/2',
            published_at=now)
        self.old_item = NewsItem.objects.create(
            ticker='AMD', headline_line='AMD: old news',
            sentiment='neutral', sentiment_score=0.0, relevance_score=0.9,
            source='Example Wire', source_url='https://example.com/3',
            published_at=now - timezone.timedelta(days=30))
        self.other_ticker = NewsItem.objects.create(
            ticker='WDGT', headline_line='WDGT: missed earnings → stock down',
            sentiment='bearish', sentiment_score=-0.4, relevance_score=0.8,
            source='Example Wire', source_url='https://example.com/4',
            published_at=now)

    def test_feed_requires_auth(self):
        anon = APIClient()
        resp = anon.get('/api/news/feed/')
        self.assertIn(resp.status_code, (401, 403))

    def test_default_filters_apply(self):
        resp = self.client.get('/api/news/feed/')
        self.assertEqual(resp.status_code, 200)
        urls = {r['source_url'] for r in resp.data['results']}
        # min_relevance=0.5 default excludes recent_low_relevance;
        # days=3 default excludes old_item
        self.assertIn(self.recent_high.source_url, urls)
        self.assertIn(self.other_ticker.source_url, urls)
        self.assertNotIn(self.recent_low_relevance.source_url, urls)
        self.assertNotIn(self.old_item.source_url, urls)

    def test_ticker_filter(self):
        resp = self.client.get('/api/news/feed/', {'ticker': 'wdgt', 'min_relevance': 0})
        self.assertEqual(resp.status_code, 200)
        tickers = {r['ticker'] for r in resp.data['results']}
        self.assertEqual(tickers, {'WDGT'})

    def test_min_relevance_and_days_params(self):
        resp = self.client.get('/api/news/feed/', {'min_relevance': 0.05, 'days': 60})
        self.assertEqual(resp.status_code, 200)
        urls = {r['source_url'] for r in resp.data['results']}
        self.assertEqual(urls, {
            self.recent_high.source_url, self.recent_low_relevance.source_url,
            self.old_item.source_url, self.other_ticker.source_url,
        })

    def test_bad_params_are_rejected(self):
        resp = self.client.get('/api/news/feed/', {'min_relevance': 'nope'})
        self.assertEqual(resp.status_code, 400)
