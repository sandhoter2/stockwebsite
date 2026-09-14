from django.db import models

# 13F filings report POSITION SNAPSHOTS (shares + market value at quarter
# end), not individual buy/sell transactions. `change_kind` (computed by
# diffing consecutive quarters) is the closest thing we have to a trade
# direction, so we map it onto a simple Buy/Sell label for display:
#   new / increased  -> "Buy"  (the filer added shares this quarter)
#   decreased / closed -> "Sell" (the filer reduced/exited the position)
# This is a simplification: a "decreased" position isn't literally one sell
# transaction, it's a net reduction that could hide interim buys and sells.
BUY_OR_SELL = {'new': 'Buy', 'increased': 'Buy', 'decreased': 'Sell', 'closed': 'Sell'}

# Conviction/activity tiers for an investor's tracked history. 13F data
# doesn't support a literal win-rate tier (we don't know cost basis or exit
# price), so this is a much softer "how much signal do we have, and how
# often do they open brand-new positions" framing rather than a
# performance judgment.
CONVICTION_TIER_LABELS = {
    'established': 'Established · deep history', 'active': 'Active filer', 'building': 'Building track record',
}


class SuperInvestor(models.Model):
    """A well-known investor/fund whose SEC Form 13F filings we track.

    13F filings are made by the management company (the "filer"), so `cik`
    is the fund/firm's SEC Central Index Key, zero-padded to 10 digits as
    SEC's APIs expect (e.g. '0001067983' for Berkshire Hathaway).
    """
    name = models.CharField(max_length=128, help_text="Well-known investor, e.g. 'Warren Buffett'")
    fund_name = models.CharField(max_length=255, help_text="Filing entity, e.g. 'Berkshire Hathaway Inc'")
    cik = models.CharField(max_length=10, unique=True,
                           help_text="SEC Central Index Key, zero-padded to 10 digits")
    is_active = models.BooleanField(default=True, help_text="Whether to keep pulling new filings for this filer")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.fund_name})"

    @property
    def short_label(self):
        """Compact display label, e.g. 'Burry (Scion)'."""
        last = self.name.split()[-1] if self.name else self.name
        fund_short = self.fund_name.split()[0] if self.fund_name else self.fund_name
        return f"{last} ({fund_short})"


class HoldingQuerySet(models.QuerySet):
    def latest_quarter_per_investor(self):
        """Map investor_id -> most recent filing_quarter present in this qs."""
        rows = (self.order_by().values('investor_id')
                .annotate(latest=models.Max('filing_quarter')))
        return {r['investor_id']: r['latest'] for r in rows}

    def moves(self, investor=None, ticker=None, quarters=2, limit=50):
        """Action-oriented, change-focused feed: for each investor's most
        recent N filing_quarters, diff each (investor, cusip) position
        against its immediately preceding quarter and return notable moves
        (new positions and largest % changes first) rather than a static
        holdings dump.
        """
        qs = self.select_related('investor')
        if investor:
            qs = qs.filter(investor_id=investor)
        if ticker:
            qs = qs.filter(ticker__iexact=ticker)

        # figure out, per investor, which `quarters` most-recent filing_quarter
        # values are in scope (so we diff exactly that trailing window)
        investor_ids = qs.order_by().values_list('investor_id', flat=True).distinct()
        scoped_quarters = {}
        for inv_id in investor_ids:
            qtrs = list(self.filter(investor_id=inv_id)
                        .order_by('-filing_quarter')
                        .values_list('filing_quarter', flat=True).distinct()[:quarters])
            scoped_quarters[inv_id] = set(qtrs)

        results = []
        for inv_id in investor_ids:
            in_scope = scoped_quarters.get(inv_id, set())
            if not in_scope:
                continue
            all_qtrs_for_inv = list(
                self.filter(investor_id=inv_id).order_by('-filing_quarter')
                .values_list('filing_quarter', flat=True).distinct())
            rows = list(qs.filter(investor_id=inv_id, filing_quarter__in=in_scope))
            for h in rows:
                # prior quarter = the filing_quarter immediately before h's,
                # in this investor's *full* filing history (not just the
                # window), so a position held for 3+ quarters still diffs
                # correctly against the quarter right before it.
                try:
                    idx = all_qtrs_for_inv.index(h.filing_quarter)
                except ValueError:
                    idx = -1
                prior_q = all_qtrs_for_inv[idx + 1] if 0 <= idx < len(all_qtrs_for_inv) - 1 else None
                prior = None
                if prior_q:
                    prior = Holding.objects.filter(
                        investor_id=inv_id, cusip=h.cusip, filing_quarter=prior_q).first()
                summary, kind, pct = h._compute_change(prior)
                if kind == 'unchanged':
                    continue
                profit_estimate, is_estimated = h._profit_estimate(prior)
                results.append({
                    'investor': h.investor_id,
                    'investor_name': h.investor.name,
                    'investor_short_label': h.investor.short_label,
                    'ticker': h.ticker or None,
                    'issuer_name': h.issuer_name,
                    'stock': h.ticker or h.issuer_name,
                    'cusip': h.cusip,
                    'filing_quarter': h.filing_quarter,
                    'filed_date': h.filed_date,
                    'shares': h.shares,
                    'market_value': h.market_value,
                    'prior_shares': prior.shares if prior else None,
                    'change_kind': kind,
                    'change_pct': pct,
                    'change_summary_line': summary,
                    'buy_or_sell': BUY_OR_SELL.get(kind),
                    'profit_estimate': profit_estimate,
                    'profit_is_estimated': is_estimated,
                })

        # notable-first ordering: new positions and closes before increases/
        # decreases, then largest absolute % change first
        kind_rank = {'new': 0, 'closed': 0, 'increased': 1, 'decreased': 1}
        results.sort(key=lambda r: (kind_rank.get(r['change_kind'], 2),
                                    -(abs(r['change_pct']) if r['change_pct'] is not None else 10**9)))
        return results[:limit]

    def investor_profile(self, investor_id):
        """Per-investor profile: activity/conviction stats + full move
        history, mirroring traderacker's Channel.stats()/breakdown()
        pattern (quick-glance numbers + a detail list) for one filer.
        Reuses moves() so the Buy/Sell + profit-estimate logic lives in one
        place; quarters=50 / limit=1000 is effectively "all history" for a
        quarterly filing (comfortably covers 12+ years).
        """
        all_moves = self.moves(investor=investor_id, quarters=50, limit=1000)

        # distinct-on-a-field queries: order_by() clears the model's default
        # multi-field Meta.ordering first so .distinct() dedupes on exactly
        # the projected column, not the full default order (the same fix
        # applied to moves() for its N-squared blowup).
        quarters_tracked = (self.filter(investor_id=investor_id).order_by()
                            .values_list('filing_quarter', flat=True).distinct().count())
        positions_tracked = (self.filter(investor_id=investor_id).order_by()
                             .values_list('cusip', flat=True).distinct().count())

        counts = {'new': 0, 'increased': 0, 'decreased': 0, 'closed': 0}
        total_profit = 0.0
        profit_rows = 0
        for m in all_moves:
            counts[m['change_kind']] = counts.get(m['change_kind'], 0) + 1
            if m['profit_estimate'] is not None:
                total_profit += m['profit_estimate']
                profit_rows += 1

        total_moves = sum(counts.values())
        conviction_pct = round(100 * counts['new'] / total_moves, 1) if total_moves else None

        if quarters_tracked < 2 or positions_tracked < 3:
            tier = 'building'
        elif quarters_tracked >= 4 and positions_tracked >= 15:
            tier = 'established'
        else:
            tier = 'active'

        return {
            'investor': investor_id,
            'quarters_tracked': quarters_tracked,
            'positions_tracked': positions_tracked,
            'moves_new': counts['new'],
            'moves_increased': counts['increased'],
            'moves_decreased': counts['decreased'],
            'moves_closed': counts['closed'],
            'total_moves': total_moves,
            'total_estimated_profit': round(total_profit, 2) if profit_rows else None,
            'profit_positions_count': profit_rows,
            'conviction_pct': conviction_pct,
            'conviction_tier': tier,
            'conviction_tier_label': CONVICTION_TIER_LABELS.get(tier),
            'moves': all_moves,
        }


class Holding(models.Model):
    """One (investor, security, filing_quarter) row from a 13F information
    table. Identity for upsert/diffing purposes is (investor, cusip,
    filing_quarter) — CUSIP is what 13F actually reports; `ticker` is a
    best-effort resolved symbol for display and is not always known.
    """
    investor = models.ForeignKey(SuperInvestor, on_delete=models.CASCADE, related_name='holdings')
    cusip = models.CharField(max_length=9, db_index=True)
    issuer_name = models.CharField(max_length=255)
    ticker = models.CharField(max_length=16, blank=True, db_index=True,
                              help_text="Best-effort resolved ticker; 13F only reports CUSIP so this can be blank")
    shares = models.BigIntegerField(default=0)
    market_value = models.BigIntegerField(default=0, help_text="Reported position value in USD")
    filing_quarter = models.DateField(help_text="Quarter-end date this holding was reported as of (e.g. 2025-06-30)")
    filed_date = models.DateField(help_text="Date the 13F-HR was actually filed with the SEC (~45 days after quarter end)")
    accession_number = models.CharField(max_length=32, blank=True, help_text="SEC EDGAR accession number of the source filing")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = HoldingQuerySet.as_manager()

    class Meta:
        ordering = ['-filing_quarter', 'investor', '-market_value']
        constraints = [
            models.UniqueConstraint(fields=['investor', 'cusip', 'filing_quarter'],
                                    name='uniq_holding_per_quarter'),
        ]
        indexes = [
            models.Index(fields=['investor', 'cusip', 'filing_quarter']),
        ]

    def __str__(self):
        return f"{self.investor.short_label}: {self.ticker or self.issuer_name} ({self.filing_quarter})"

    @property
    def display_symbol(self):
        return self.ticker or self.issuer_name

    def _prior_holding(self):
        prior_q = (Holding.objects.filter(
                    investor_id=self.investor_id, filing_quarter__lt=self.filing_quarter)
                   .order_by('-filing_quarter').values_list('filing_quarter', flat=True).first())
        if not prior_q:
            return None
        return Holding.objects.filter(
            investor_id=self.investor_id, cusip=self.cusip, filing_quarter=prior_q).first()

    def _compute_change(self, prior):
        """Returns (summary_line, kind, pct_change) comparing this holding
        to `prior` (same investor+cusip, previous filing_quarter row, or
        None if this is the first quarter we've seen this position)."""
        label = self.investor.short_label
        sym = self.display_symbol
        mv = self.market_value or 0

        if prior is None or not prior.shares:
            return (f"{label}: opened new position in {sym}, ~${mv:,.0f} market value",
                    'new', None)
        if not self.shares:
            return (f"{label}: closed position in {sym} (was ~${prior.market_value:,.0f})",
                    'closed', -100.0)
        if prior.shares == self.shares:
            return (f"{label}: held {sym} steady at {self.shares:,} shares", 'unchanged', 0.0)

        pct = round(100 * (self.shares - prior.shares) / prior.shares, 1)
        if pct > 0:
            return (f"{label}: increased {sym} position by {pct}% (~${mv:,.0f} now)",
                    'increased', pct)
        return (f"{label}: decreased {sym} position by {abs(pct)}% (~${mv:,.0f} now)",
                'decreased', pct)

    def _profit_estimate(self, prior):
        """Rough, clearly-labeled profit ESTIMATE for this position vs.
        `prior` quarter's row (same investor+cusip). 13F filings report
        share counts + point-in-time market value, not trade prices or
        cost basis, so this is never an exact P&L figure.

        Approach: isolate the price-driven change in value from the
        share-count-driven change by applying the per-share value delta to
        only the shares held across BOTH quarters (`base_shares` = the
        smaller of the two share counts):
            price_prior = prior.market_value / prior.shares
            price_now   = self.market_value / self.shares
            profit ~= (price_now - price_prior) * min(prior.shares, self.shares)
        When shares are unchanged this reduces to the exact market_value
        delta (an "unrealized gain/loss this quarter" reading). When shares
        changed, it's a fuzzier approximation that ignores gains/losses on
        the newly added/removed shares themselves.

        Returns (profit_estimate, is_estimated). profit_estimate is None
        (never a fabricated guess) when there's no comparable basis: a
        brand-new position (no prior quarter) or a fully closed position
        (13F doesn't report the sale price, so we can't estimate proceeds).
        """
        if prior is None or not prior.shares or not self.shares:
            return None, True
        base_shares = min(prior.shares, self.shares)
        price_prior = prior.market_value / prior.shares
        price_now = self.market_value / self.shares
        return round((price_now - price_prior) * base_shares, 2), True

    @property
    def change_summary_line(self):
        summary, _, _ = self._compute_change(self._prior_holding())
        return summary

    @property
    def change_kind(self):
        _, kind, _ = self._compute_change(self._prior_holding())
        return kind

    @property
    def change_pct(self):
        _, _, pct = self._compute_change(self._prior_holding())
        return pct

    @property
    def buy_or_sell(self):
        return BUY_OR_SELL.get(self.change_kind)

    @property
    def profit_estimate(self):
        estimate, _ = self._profit_estimate(self._prior_holding())
        return estimate

    @property
    def profit_is_estimated(self):
        _, is_estimated = self._profit_estimate(self._prior_holding())
        return is_estimated
