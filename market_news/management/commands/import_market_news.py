"""Fetch Alpha Vantage NEWS_SENTIMENT and curate it into terse, per-ticker
NewsItem rows.

Alpha Vantage docs: https://www.alphavantage.co/documentation/#news-sentiment

Response shape (confirmed against a live call, Sep 2026):
{
  "items": "50",
  "sentiment_score_definition": "...",
  "relevance_score_definition": "...",
  "feed": [
    {
      "title": str,
      "url": str,
      "time_published": "YYYYMMDD'T'HHMMSS",
      "authors": [str, ...],
      "summary": str,
      "banner_image": str,
      "source": str,
      "category_within_source": str,
      "source_domain": str,
      "topics": [{"topic": str, "relevance_score": "0.xxxxxx"}, ...],
      "overall_sentiment_score": float,
      "overall_sentiment_label": str,
      "ticker_sentiment": [
        {
          "ticker": str,
          "relevance_score": "0.xxxxxx",
          "ticker_sentiment_score": "0.xxxxxx",
          "ticker_sentiment_label": str,
        },
        ...
      ],
    },
    ...
  ],
}

We fan each article out into one NewsItem per ticker_sentiment entry whose
relevance_score clears --min-relevance, reshaping Alpha Vantage's own
title/summary into a terse "TICKER: what happened -> why it matters" line
(simple deterministic string extraction — no external LLM call).
"""
import datetime as dt
import os
import re

import requests
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone as dj_timezone

from market_news.models import NewsItem

ALPHAVANTAGE_URL = 'https://www.alphavantage.co/query'
DEFAULT_MIN_RELEVANCE = 0.3

_SENTIMENT_BUCKETS = {
    'Bullish': 'bullish', 'Somewhat-Bullish': 'bullish',
    'Bearish': 'bearish', 'Somewhat-Bearish': 'bearish',
    'Neutral': 'neutral',
}

# splits on sentence-ending punctuation followed by whitespace + a capital
# letter / digit, so we don't break on abbreviations like "U.S." mid-clause
_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9])')

MAX_LINE_LEN = 280


def as_float(v):
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_time_published(raw):
    """'20260913T132613' -> aware datetime in UTC. Returns None if unparseable."""
    if not raw:
        return None
    try:
        naive = dt.datetime.strptime(raw, '%Y%m%dT%H%M%S')
    except ValueError:
        return None
    return dj_timezone.make_aware(naive, dt.timezone.utc)


def sentiment_bucket(label):
    return _SENTIMENT_BUCKETS.get(label, 'neutral')


def _clip(text, limit):
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:max(0, limit - 1)].rstrip() + '…'


def condense_summary(title, summary):
    """Reshape Alpha Vantage's title/summary into a short "what happened ->
    why it matters" fragment (no ticker prefix yet — see build_headline_line).

    Deterministic, string-level only: take the first sentence of the summary
    as "what happened"; if a second sentence exists, take a short lead-in of
    it as "why it matters" and join with an arrow. Falls back to the title
    when there's no usable summary.
    """
    summary = (summary or '').strip()
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(summary) if s.strip()]
    if not sentences:
        return _clip(title or '', 160)

    what = sentences[0].rstrip('.!? ')
    if len(sentences) > 1:
        why = sentences[1].rstrip('.!? ')
        # keep "why" short — it's a supporting clause, not a second headline
        why_words = why.split()
        if len(why_words) > 14:
            why = ' '.join(why_words[:14]) + '…'
        return f"{_clip(what, 120)} → {_clip(why, 90)}"
    return _clip(what, 160)


def build_headline_line(ticker, title, summary):
    condensed = condense_summary(title, summary)
    line = f"{ticker}: {condensed}"
    return _clip(line, MAX_LINE_LEN)


def extract_news_items(payload, min_relevance=DEFAULT_MIN_RELEVANCE):
    """Pure function: Alpha Vantage NEWS_SENTIMENT JSON -> list of dicts
    ready for NewsItem.objects.update_or_create(**kwargs). Skips articles/
    tickers below the relevance threshold or missing required fields.
    """
    out = []
    for article in payload.get('feed') or []:
        url = (article.get('url') or '').strip()
        published_at = parse_time_published(article.get('time_published'))
        if not url or not published_at:
            continue
        title = article.get('title') or ''
        summary = article.get('summary') or ''
        source = article.get('source') or ''

        for ts in article.get('ticker_sentiment') or []:
            ticker = (ts.get('ticker') or '').strip().upper()
            relevance = as_float(ts.get('relevance_score'))
            if not ticker or relevance is None or relevance < min_relevance:
                continue
            out.append({
                'ticker': ticker,
                'source_url': url,
                'headline_line': build_headline_line(ticker, title, summary),
                'sentiment': sentiment_bucket(ts.get('ticker_sentiment_label')),
                'sentiment_score': as_float(ts.get('ticker_sentiment_score')),
                'relevance_score': relevance,
                'source': source,
                'published_at': published_at,
            })
    return out


class Command(BaseCommand):
    help = ('Fetch Alpha Vantage NEWS_SENTIMENT and upsert curated, terse '
           'per-ticker NewsItem rows (dedup on source_url+ticker).')

    def add_arguments(self, parser):
        parser.add_argument('--tickers', default=None,
                            help='Comma-separated tickers to request, e.g. AAPL,MSFT,AMD '
                                 '(omitted: Alpha Vantage returns its general top-news feed)')
        parser.add_argument('--topics', default=None,
                            help='Comma-separated Alpha Vantage topics, e.g. technology,earnings')
        parser.add_argument('--limit', type=int, default=200,
                            help='Max articles to request from Alpha Vantage (default 200, their max 1000)')
        parser.add_argument('--min-relevance', type=float, default=DEFAULT_MIN_RELEVANCE,
                            help=f'Drop ticker/article pairs below this relevance_score '
                                 f'(default {DEFAULT_MIN_RELEVANCE})')

    def handle(self, *args, **opts):
        api_key = os.environ.get('ALPHAVANTAGE_API_KEY')
        if not api_key:
            raise CommandError(
                "ALPHAVANTAGE_API_KEY is not set. Sign up for a free Alpha Vantage API "
                "key at https://www.alphavantage.co/support/#api-key and export it, e.g.\n"
                "    export ALPHAVANTAGE_API_KEY=your_key_here\n"
                "then re-run: python manage.py import_market_news")

        params = {
            'function': 'NEWS_SENTIMENT',
            'apikey': api_key,
            'limit': str(opts['limit']),
            'sort': 'LATEST',
        }
        if opts.get('tickers'):
            params['tickers'] = opts['tickers']
        if opts.get('topics'):
            params['topics'] = opts['topics']

        resp = requests.get(ALPHAVANTAGE_URL, params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()

        if 'Error Message' in payload or 'Note' in payload or 'Information' in payload:
            # Alpha Vantage reports rate-limit / bad-request errors with a 200
            # status and one of these keys instead of a 'feed' key
            msg = payload.get('Error Message') or payload.get('Note') or payload.get('Information')
            raise CommandError(f'Alpha Vantage error: {msg}')

        rows = extract_news_items(payload, min_relevance=opts['min_relevance'])

        created, updated = 0, 0
        for row in rows:
            _, was_created = NewsItem.objects.update_or_create(
                source_url=row['source_url'], ticker=row['ticker'],
                defaults={k: v for k, v in row.items() if k not in ('source_url', 'ticker')},
            )
            created += was_created
            updated += not was_created

        self.stdout.write(self.style.SUCCESS(
            f"Fetched {len(payload.get('feed') or [])} articles, "
            f"kept {len(rows)} ticker-relevant lines "
            f"({created} created, {updated} updated)."))
