from django.db import models


def format_amount(n):
    """Compact dollar formatting for a disclosure amount, e.g. 1_000_000 -> '$1M'."""
    if n is None:
        return '?'
    n = int(n)
    if n >= 1_000_000:
        val = n / 1_000_000
        return f"${val:.1f}M".replace('.0M', 'M')
    if n >= 1_000:
        val = n / 1_000
        return f"${val:.0f}K"
    return f"${n:,}"


class CongressTradeQuerySet(models.QuerySet):
    """Fat-queryset analytics for the REST views (thin controllers), same
    pattern as traderacker.TradeQuerySet."""

    def recent(self, days=45):
        from datetime import timedelta

        from django.utils import timezone
        cutoff = timezone.localdate() - timedelta(days=days)
        return self.filter(disclosure_date__gte=cutoff)

    def notable(self, days=60, limit=20):
        """Curated 'largest recent trades' feed — the action-oriented
        default view instead of a dump of every disclosure."""
        return list(self.recent(days=days).order_by('-amount_max', '-disclosure_date')[:limit])


class CongressTrade(models.Model):
    """One disclosed stock transaction by a member of the US House or
    Senate, sourced from public STOCK Act filings (House Clerk periodic
    transaction reports / Senate eFD). Disclosures report a dollar *range*,
    not an exact amount, so amount_min/amount_max are stored separately
    rather than as one figure."""

    CHAMBER_CHOICES = [('House', 'House'), ('Senate', 'Senate')]
    PARTY_CHOICES = [('D', 'Democrat'), ('R', 'Republican'), ('I', 'Independent'), ('?', 'Unknown')]
    TRANSACTION_CHOICES = [
        ('buy', 'Purchase'), ('sell', 'Sale'), ('exchange', 'Exchange'),
    ]
    TRANSACTION_VERB = {'buy': 'bought', 'sell': 'sold', 'exchange': 'exchanged'}

    politician_name = models.CharField(max_length=128, db_index=True)
    party = models.CharField(max_length=1, choices=PARTY_CHOICES, default='?')
    chamber = models.CharField(max_length=6, choices=CHAMBER_CHOICES, db_index=True)
    state = models.CharField(max_length=2, blank=True)

    ticker = models.CharField(max_length=12, blank=True, db_index=True,
                              help_text="Ticker symbol, blank for non-traded assets (e.g. private funds)")
    asset_description = models.CharField(max_length=255,
                                         help_text="Asset name as printed on the disclosure")

    transaction_type = models.CharField(max_length=8, choices=TRANSACTION_CHOICES)
    amount_min = models.IntegerField()
    amount_max = models.IntegerField()

    transaction_date = models.DateField(help_text="Date the member actually made the trade")
    disclosure_date = models.DateField(help_text="Date the trade was publicly disclosed (lags transaction_date)")

    filing_url = models.URLField(max_length=500, blank=True,
                                 help_text="Link to the source filing (PDF)")
    source_doc_id = models.CharField(max_length=64, blank=True,
                                     help_text="Filing id from the source system, for traceability")

    created_at = models.DateTimeField(auto_now_add=True)

    objects = CongressTradeQuerySet.as_manager()

    class Meta:
        ordering = ['-disclosure_date', '-transaction_date']
        constraints = [
            models.UniqueConstraint(
                fields=['chamber', 'source_doc_id', 'ticker', 'transaction_date',
                        'transaction_type', 'amount_min', 'amount_max'],
                name='uniq_congress_trade_row',
            ),
        ]
        indexes = [
            models.Index(fields=['disclosure_date']),
            models.Index(fields=['transaction_date']),
        ]

    def __str__(self):
        return self.summary_line

    @property
    def amount_range_label(self):
        return f"{format_amount(self.amount_min)}–{format_amount(self.amount_max)}"

    @property
    def summary_line(self):
        """One terse, pre-formatted line for the frontend — the product
        requirement is 'precise and action-oriented', not a wide table.

        e.g. "Pelosi (D) bought NVDA $1M–5M · disclosed 2026-08-15 (trade date 2026-07-28)"
        """
        who = f"{self.politician_name} ({self.party})" if self.party != '?' else self.politician_name
        verb = self.TRANSACTION_VERB.get(self.transaction_type, self.transaction_type)
        what = self.ticker or self.asset_description
        disclosed = self.disclosure_date.isoformat() if self.disclosure_date else '?'
        traded = self.transaction_date.isoformat() if self.transaction_date else '?'
        return (f"{who} {verb} {what} {self.amount_range_label} · "
                f"disclosed {disclosed} (trade date {traded})")
