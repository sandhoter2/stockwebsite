from django.db import models
from django.db.models import Count, Q, Sum

# Reuse traderacker's shared trust-tier/confidence-interval helpers rather
# than reimplementing win-rate scoring -- same math the channel leaderboard
# already uses, applied here to politicians' closed round-trips.
from traderacker.models import TIER_LABELS, trust_tier, wilson_lower_bound  # noqa: F401


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

    def compute_profit_estimates(self, price_fn=None, historical_fn=None, progress=None):
        """FIFO-match each politician+ticker's buy/sell rows and stamp every
        row with an *estimated* profit (see congress_trades.market's module
        docstring for the approximation this relies on), mirroring how
        traderacker.PaperTrade marks a position to market.

        For each (politician, ticker) group, ordered chronologically:
          * a 'sell' closes the oldest still-open 'buy' (FIFO) — both rows
            get the same `realized_profit`, computed as the ticker's actual
            % price move between the two transaction dates applied to the
            *buy's* disclosed notional (amount_mid);
          * a 'buy' left unmatched (still open) gets `unrealized_profit`,
            the ticker's % move from its transaction date to today applied
            to its own notional;
          * a 'sell' with no open buy to close against (e.g. a pre-existing
            holding sold, or a short we never saw the buy for) is left with
            no profit figure — there's nothing to compute a return against.
        'exchange' rows are skipped entirely (not a simple buy/sell).

        Historical/current prices are cached per (ticker, date) / ticker so
        a politician who traded the same stock repeatedly doesn't re-fetch.
        Returns the number of rows updated.
        """
        from collections import defaultdict

        from .market import get_price as _get_price
        from .market import historical_price as _historical_price
        price_fn = price_fn or _get_price
        historical_fn = historical_fn or _historical_price

        hist_cache, current_cache = {}, {}

        def hist(ticker, d):
            key = (ticker, d)
            if key not in hist_cache:
                hist_cache[key] = historical_fn(ticker, d)
            return hist_cache[key]

        def current(ticker):
            if ticker not in current_cache:
                price, _src = price_fn(ticker)
                current_cache[ticker] = price
            return current_cache[ticker]

        groups = defaultdict(list)
        qs = self.exclude(ticker='').exclude(transaction_type='exchange')
        for t in qs.order_by('transaction_date', 'id'):
            groups[(t.politician_name, t.ticker)].append(t)

        to_update = []
        n_groups = len(groups)
        for gi, ((politician, ticker), trades) in enumerate(groups.items()):
            if progress:
                progress(gi, n_groups, politician, ticker)
            open_buys = []
            for t in trades:
                if t.transaction_type == 'buy':
                    open_buys.append(t)
                elif t.transaction_type == 'sell' and open_buys:
                    buy = open_buys.pop(0)
                    buy_px = hist(ticker, buy.transaction_date)
                    sell_px = hist(ticker, t.transaction_date)
                    buy.matched_trade = t
                    t.matched_trade = buy
                    if buy_px and sell_px:
                        pct = (sell_px - buy_px) / buy_px
                        profit = round(buy.amount_mid * pct, 2)
                        buy.realized_profit = profit
                        buy.unrealized_profit = None
                        buy.profit_kind = 'realized'
                        t.realized_profit = profit
                        t.profit_kind = 'realized'
                    to_update.extend([buy, t])
            for buy in open_buys:
                buy_px = hist(ticker, buy.transaction_date)
                cur_px = current(ticker)
                if buy_px and cur_px:
                    pct = (cur_px - buy_px) / buy_px
                    buy.unrealized_profit = round(buy.amount_mid * pct, 2)
                    buy.profit_kind = 'unrealized'
                    to_update.append(buy)

        if to_update:
            self.model.objects.bulk_update(
                to_update,
                ['realized_profit', 'unrealized_profit', 'profit_kind', 'matched_trade'],
                batch_size=500,
            )
        return len(to_update)

    def politician_breakdown(self):
        """Per-politician aggregate rows for a leaderboard/profile list —
        same shape/spirit as traderacker.TradeQuerySet.breakdown() for
        channels: trade counts, win rate on *closed* round-trips, realized/
        unrealized totals, and a reused trust tier.

        A round-trip's realized_profit is stamped on both its buy and sell
        row (see compute_profit_estimates), so aggregates only look at the
        'buy' side to avoid double-counting each closed position twice.
        """
        rows = (self.exclude(politician_name='')
                .order_by().values('politician_name', 'party', 'chamber')
                .annotate(
                    n_trades=Count('id'),
                    n_buys=Count('id', filter=Q(transaction_type='buy')),
                    n_sells=Count('id', filter=Q(transaction_type='sell')),
                    n_closed=Count('id', filter=Q(transaction_type='buy', profit_kind='realized')),
                    n_wins=Count('id', filter=Q(transaction_type='buy', profit_kind='realized',
                                                realized_profit__gt=0)),
                    n_open=Count('id', filter=Q(transaction_type='buy', profit_kind='unrealized')),
                    sum_realized=Sum('realized_profit', filter=Q(transaction_type='buy')),
                    sum_unrealized=Sum('unrealized_profit', filter=Q(transaction_type='buy')),
                ))
        out = []
        for r in rows:
            closed = r['n_closed']
            wins = r['n_wins']
            win_rate = round(100 * wins / closed, 1) if closed else None
            out.append({
                'politician_name': r['politician_name'],
                'party': r['party'],
                'chamber': r['chamber'],
                'trades': r['n_trades'],
                'buys': r['n_buys'],
                'sells': r['n_sells'],
                'closed': closed,
                'open': r['n_open'],
                'wins': wins,
                'losses': closed - wins,
                'win_rate': win_rate,
                'confidence_score': wilson_lower_bound(wins, closed),
                'realized_profit': round(r['sum_realized'], 2) if r['sum_realized'] is not None else None,
                'unrealized_profit': round(r['sum_unrealized'], 2) if r['sum_unrealized'] is not None else None,
            })
        for o in out:
            o['tier'] = trust_tier(o['win_rate'], o['closed'])
            o['tier_label'] = TIER_LABELS.get(o['tier'])
        out.sort(key=lambda x: (x['realized_profit'] if x['realized_profit'] is not None else -1e18),
                 reverse=True)
        return out


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

    # ---- profit estimate (see congress_trades.market + compute_profit_estimates) ----
    # Disclosures give a dollar *range*, not an exact amount or per-share
    # price, so everything below is an ESTIMATE: the range midpoint stands
    # in for the traded notional, and profit is that notional's share of
    # the stock's real subsequent % price move (mirrors how
    # traderacker.PaperTrade marks a position to market, just without a
    # real entry price to start from).
    PROFIT_KIND_CHOICES = [('realized', 'Realized (closed round-trip)'),
                           ('unrealized', 'Unrealized (still open, marked to market)')]
    realized_profit = models.FloatField(
        null=True, blank=True,
        help_text="Estimated $ profit once this position was closed by a matching sale (FIFO)")
    unrealized_profit = models.FloatField(
        null=True, blank=True,
        help_text="Estimated $ profit marking this still-open buy to the latest market price")
    profit_kind = models.CharField(max_length=10, choices=PROFIT_KIND_CHOICES, blank=True)
    matched_trade = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name='matched_by',
                                      help_text="The FIFO-paired buy/sell row this round-trip was closed against")

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
    def amount_mid(self):
        """Midpoint of the disclosed amount range — stand-in for the actual
        (never-disclosed) transaction dollar value."""
        return (self.amount_min + self.amount_max) / 2.0

    @property
    def profit(self):
        """The one profit figure to show for this row: realized if this
        position (or its matching leg) has closed, else unrealized if it's
        still open and priced, else None if it hasn't been estimated (not
        yet computed, or no matching buy / no price data available)."""
        if self.profit_kind == 'realized':
            return self.realized_profit
        if self.profit_kind == 'unrealized':
            return self.unrealized_profit
        return None

    @property
    def profit_is_realized(self):
        return self.profit_kind == 'realized'

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
