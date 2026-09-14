from django.db import models


class NewsItemQuerySet(models.QuerySet):
    """Query helpers used by the /api/news/feed/ view (thin controller)."""

    def for_ticker(self, ticker):
        if not ticker:
            return self
        return self.filter(ticker__iexact=ticker.strip())

    def min_relevance(self, threshold):
        if threshold is None:
            return self
        return self.filter(relevance_score__gte=threshold)

    def recent(self, since):
        if since is None:
            return self
        return self.filter(published_at__gte=since)


class NewsItem(models.Model):
    """One curated, action-oriented news line for a single ticker.

    Sourced from Alpha Vantage's NEWS_SENTIMENT API. Alpha Vantage returns
    one *article* tagged with zero or more tickers, each carrying its own
    relevance/sentiment scores — we fan that out into one NewsItem per
    (article, ticker) pair so the feed can filter/rank per ticker and so
    each row is a single terse, ticker-specific line (e.g. "AMD: acquired
    Taalas -> strengthens laptop chip lineup") rather than a raw dump of the
    article. Only pairs above a relevance threshold are kept at import time
    (see management/commands/import_market_news.py) — curation, not a mirror
    of the upstream feed.
    """
    SENTIMENT_CHOICES = [
        ('bullish', 'Bullish'), ('bearish', 'Bearish'), ('neutral', 'Neutral'),
    ]

    ticker = models.CharField(max_length=16, db_index=True)
    headline_line = models.CharField(
        max_length=280,
        help_text="Terse, action/impact-oriented one-liner: 'TICKER: what happened -> why it matters'")
    sentiment = models.CharField(max_length=8, choices=SENTIMENT_CHOICES, default='neutral')
    sentiment_score = models.FloatField(
        null=True, blank=True,
        help_text="Raw Alpha Vantage ticker_sentiment_score, -1 (bearish) .. 1 (bullish)")
    relevance_score = models.FloatField(
        help_text="Alpha Vantage per-ticker relevance_score, 0..1")
    source = models.CharField(max_length=128, blank=True)
    source_url = models.URLField(max_length=1000)
    published_at = models.DateTimeField(help_text="When the source article was published")
    fetched_at = models.DateTimeField(auto_now_add=True)

    objects = NewsItemQuerySet.as_manager()

    class Meta:
        ordering = ['-published_at', '-relevance_score']
        constraints = [
            models.UniqueConstraint(fields=['source_url', 'ticker'], name='uniq_news_item'),
        ]
        indexes = [
            models.Index(fields=['ticker', '-published_at']),
        ]

    def __str__(self):
        return self.headline_line
