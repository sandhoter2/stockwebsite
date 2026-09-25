import math
import re
from datetime import date as _date
from datetime import timedelta

from django.db import models
from django.db.models import Count, Q, Sum
from django.utils import timezone


def trust_tier(rate, sample):
    """Plain-language verdict for a channel's win-rate/hit-rate, so users see
    a judgment instead of having to read a bare percentage + sample size.

    'sample' is the number of *booked/validated* outcomes behind `rate` — a
    high percentage on a handful of trades is a streak, not a track record.
    """
    if rate is None or not sample:
        return 'building'
    if sample < 5:
        return 'building'
    if rate >= 65 and sample >= 10:
        return 'top'
    if rate >= 50:
        return 'solid'
    if rate < 35 and sample >= 10:
        return 'avoid'
    return 'watch'


TIER_LABELS = {
    'top': 'Top tier', 'solid': 'Solid', 'watch': 'Watch',
    'avoid': 'Avoid', 'building': 'Building track record',
}


def wilson_lower_bound(successes, n, z=1.96):
    """95%-confidence lower bound on a win rate (Wilson score interval),
    as a 0-100 percentage. Unlike a raw percentage, this naturally penalizes
    small samples — 100% on 3 trades scores far lower than 90% on 56 —
    so it can be used to rank/tier channels without a hard trade-count cutoff.
    Returns None when there's no sample to score.
    """
    if not n:
        return None
    phat = successes / n
    denom = 1 + z * z / n
    center = phat + z * z / (2 * n)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
    return round(100 * max(0.0, (center - margin) / denom), 1)


class Channel(models.Model):
    """A Telegram channel tracked by the trade tracker."""
    STYLE_CHOICES = [
        ('auto', 'Auto-detect'), ('options', 'Options-first (@ premium)'),
        ('cash', 'Cash equity (Buy X above N)'), ('crypto', 'Crypto futures (LONG/SHORT Nx)'),
        ('mixed', 'Mixed multi-asset'), ('promo', 'Mostly promo/news (skip)'),
    ]
    peer = models.CharField(max_length=32, unique=True, help_text="Telegram peer id, e.g. -1001845341480")
    name = models.CharField(max_length=255)
    short = models.CharField(max_length=64, blank=True)
    is_active = models.BooleanField(default=True)
    style = models.CharField(max_length=12, choices=STYLE_CHOICES, default='auto',
                             help_text="Consumer's typical posting style, drives parsing")
    style_notes = models.TextField(blank=True,
                                   help_text="Free-text notes on this consumer's format for easier parsing")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class TradeQuerySet(models.QuerySet):
    """Fat-model analytics used by the REST views (thin controllers)."""

    def in_range(self, date_from=None, date_to=None):
        qs = self
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        return qs

    def sectors(self, sectors):
        """Restrict to a list of asset_class values (empty/None → no-op)."""
        if not sectors:
            return self
        return self.filter(asset_class__in=list(sectors))

    def _channel_weights(self):
        """Map channel_id -> accuracy weight in [0, 1] for consensus scoring.

        Backed by each channel's confidence-adjusted win rate (Wilson lower
        bound) over its *entire* trade history (not just this queryset's
        scope), so a channel's credibility doesn't reset per date-range/
        sector filter. Channels without enough booked trades to trust get a
        neutral 0.5 weight so new/unproven channels aren't zeroed out.
        """
        weights = {}
        for row in Trade.objects.breakdown():
            score = row['confidence_score'] if row['booked'] >= 5 else None
            weights[row['channel']] = (score / 100.0) if score is not None else 0.5
        return weights

    def picks(self, limit=25):
        """Cross-channel consensus: per normalized symbol, BUY vs SELL counts,
        both raw (one vote per channel) and accuracy-weighted (each channel's
        vote scaled by its verified win-rate) so the two can be compared.

        'buy' = channels leaning long (BUY / CALL(up)); 'sell' = channels
        leaning short (SELL / PUT(down)). A symbol is one recommendation per
        channel (distinct) so a single noisy channel can't dominate.
        """
        from django.db.models.functions import Upper
        weights = self._channel_weights()
        rows = (self.exclude(entry=None)
                .annotate(sym=Upper('trade'))
                .values('sym', 'channel_id')
                .annotate(
                    buy=Count('id', filter=Q(direction__in=['BUY', 'CALL (up)'])),
                    sell=Count('id', filter=Q(direction__in=['SELL', 'PUT (down)'])),
                ))
        # collapse duplicate root symbols (e.g. NIFTY 24000 CE + NIFTY 25000 PE → NIFTY)
        merged = {}
        for r in rows:
            sym = r['sym'].split()[0] if r['sym'] else ''
            if not sym:
                continue
            m = merged.setdefault(sym, {'symbol': sym, 'buy': 0, 'sell': 0,
                                        'buyers': 0, 'sellers': 0,
                                        'weighted_buy': 0.0, 'weighted_sell': 0.0})
            w = weights.get(r['channel_id'], 0.5)
            if r['buy']:
                m['buy'] += r['buy']; m['buyers'] += 1
                m['weighted_buy'] += r['buy'] * w
            if r['sell']:
                m['sell'] += r['sell']; m['sellers'] += 1
                m['weighted_sell'] += r['sell'] * w
        for x in merged.values():
            x['net'] = x['buy'] - x['sell']
            x['weighted_buy'] = round(x['weighted_buy'], 2)
            x['weighted_sell'] = round(x['weighted_sell'], 2)
            x['weighted_net'] = round(x['weighted_buy'] - x['weighted_sell'], 2)
            raw_side = 'BUY' if x['net'] > 0 else ('SELL' if x['net'] < 0 else None)
            weighted_side = ('BUY' if x['weighted_net'] > 0 else
                             ('SELL' if x['weighted_net'] < 0 else None))
            # flags when raw consensus and accuracy-weighted consensus disagree,
            # e.g. many low-accuracy channels outvoting a few high-accuracy ones
            x['diverges'] = bool(raw_side and weighted_side and raw_side != weighted_side)
        # Sorted by accuracy-weighted conviction (|weighted_net|), not raw
        # chatter volume: a symbol only a couple of high-win-rate channels
        # agree on should outrank one twenty low-accuracy channels are
        # yelling about.
        result = sorted(merged.values(), key=lambda x: abs(x['weighted_net']), reverse=True)
        return result[:limit]

    def todays_calls(self, hours=24):
        """Recent trade calls across all channels ('today's calls' live feed),
        sorted by the posting channel's trust tier / confidence score so the
        most credible calls surface first.
        """
        cutoff = timezone.now() - timedelta(hours=hours)
        weights = {r['channel']: r for r in Trade.objects.breakdown()}
        tier_rank = {'top': 0, 'solid': 1, 'watch': 2, 'building': 3, 'avoid': 4}
        calls = (self.filter(posted_at__gte=cutoff)
                 .select_related('channel').order_by('-posted_at'))
        out = []
        for t in calls:
            w = weights.get(t.channel_id, {})
            tier = w.get('tier', 'building')
            out.append({
                'id': t.id, 'channel': t.channel_id,
                'channel_name': t.channel.short or t.channel.name,
                'trade': t.trade, 'direction': t.direction, 'entry': t.entry,
                'target': t.target, 'stop_loss': t.stop_loss, 'status': t.status,
                'asset_class': t.asset_class,
                'posted_at': t.posted_at.isoformat() if t.posted_at else None,
                'channel_success_rate': w.get('success_rate'),
                'channel_booked': w.get('booked', 0),
                'channel_confidence_score': w.get('confidence_score'),
                'channel_tier': tier,
                'channel_tier_label': TIER_LABELS.get(tier),
            })
        out.sort(key=lambda r: (tier_rank.get(r['channel_tier'], 5),
                                -(r['channel_confidence_score'] or 0)))
        return out

    def stats(self):
        """Quick-glance track-record dict for the rows in this queryset."""
        trades = list(self.values('date', 'trade', 'entry', 'realized',
                                  'unrealized', 'status'))
        closed = [t for t in trades if t['status'] == 'Closed']
        open_ = [t for t in trades if t['status'] == 'Open']
        booked = [t for t in closed if t['realized'] is not None]
        wins = [t for t in booked if t['realized'] > 0]
        losses = [t for t in booked if t['realized'] < 0]
        flat = [t for t in booked if t['realized'] == 0]

        invested = sum(t['entry'] or 0 for t in trades if t['entry'] is not None)
        realized = sum(t['realized'] or 0 for t in booked)
        unrealized = sum(t['unrealized'] or 0 for t in open_
                         if t['unrealized'] is not None)
        avg_win = round(sum(t['realized'] for t in wins) / len(wins), 2) if wins else None
        avg_loss = round(sum(t['realized'] for t in losses) / len(losses), 2) if losses else None
        best = max(booked, key=lambda t: t['realized'], default=None)
        worst = min(booked, key=lambda t: t['realized'], default=None)

        months = {}
        for t in booked:
            key = t['date'].strftime('%Y-%m') if t['date'] else 'undated'
            m = months.setdefault(key, {'realized': 0, 'trades': 0, 'wins': 0})
            m['realized'] += t['realized']
            m['trades'] += 1
            if t['realized'] > 0:
                m['wins'] += 1
        monthly = [
            {'month': k, 'trades': v['trades'], 'wins': v['wins'],
             'realized': round(v['realized'], 2),
             'success_rate': round(100 * v['wins'] / v['trades'], 1)}
            for k, v in sorted(months.items(), key=lambda x: x[0], reverse=True)
        ][:12]

        curve, run = [], 0.0
        for t in sorted(booked, key=lambda x: (x['date'] or _date.min)):
            run += t['realized']
            curve.append({'d': t['date'].isoformat() if t['date'] else None,
                          'cum': round(run, 2)})

        n = len(booked)
        return {
            'trades': len(trades),
            'open': len(open_),
            'closed': len(closed),
            'invested': round(invested, 2),
            'realized': round(realized, 2),
            'unrealized': round(unrealized, 2),
            'return_pct': round(100 * realized / invested, 1) if invested else None,
            'success_rate': round(100 * len(wins) / n, 1) if n else None,
            'wins': len(wins), 'losses': len(losses), 'flat': len(flat),
            'avg_win': avg_win, 'avg_loss': avg_loss,
            'best': {k: best[k] for k in ('trade', 'realized', 'date')} if best else None,
            'worst': {k: worst[k] for k in ('trade', 'realized', 'date')} if worst else None,
            'monthly': monthly,
            'equity_curve': curve[-120:],
        }

    def breakdown(self):
        """Per-channel aggregate rows (single grouped query — no N+1)."""
        rows = (self.order_by().values('channel_id', 'channel__name',
                                       'channel__short')
                .annotate(
                    n_trades=Count('id'),
                    n_open=Count('id', filter=Q(status='Open')),
                    sum_realized=Sum('realized'),
                    sum_unrealized=Sum('unrealized', filter=Q(status='Open')),
                    sum_invested=Sum('entry'),
                    n_wins=Count('id', filter=Q(status='Closed', realized__gt=0)),
                    n_losses=Count('id', filter=Q(status='Closed', realized__lt=0)),
                    n_booked=Count('id', filter=Q(status='Closed',
                                                  realized__isnull=False)),
                ))
        out = []
        for r in rows:
            out.append({
                'channel': r['channel_id'],
                'name': r['channel__name'],
                'short': r['channel__short'],
                'trades': r['n_trades'],
                'open': r['n_open'],
                'realized': round(r['sum_realized'], 2) if r['sum_realized'] is not None else None,
                'unrealized': round(r['sum_unrealized'], 2) if r['sum_unrealized'] is not None else None,
                'invested': round(r['sum_invested'], 2) if r['sum_invested'] is not None else None,
                'wins': r['n_wins'], 'losses': r['n_losses'], 'booked': r['n_booked'],
                'success_rate': round(100 * r['n_wins'] / r['n_booked'], 1) if r['n_booked'] else None,
            })
        for o in out:
            o['confidence_score'] = wilson_lower_bound(o['wins'], o['booked'])
            o['tier'] = trust_tier(o['success_rate'], o['booked'])
            o['tier_label'] = TIER_LABELS.get(o['tier'])
        return out


# Exchange-set lot sizes / P&L multipliers, researched against current
# (Sep 2026) NSE/MCX contract specs -- `realized` on a Trade row is always
# the raw per-unit price difference (channel calls state a price, not a
# contract), so real money = realized * this multiplier. Exchanges revise
# these periodically (NSE's own Jan 2026 index-lot revision is a recent
# example) -- ponytail: hardcoded snapshot, not a live feed; re-verify
# against nseindia.com/mcxindia.com if a shown value looks stale.
#
# Index/commodity multiplier IS the lot size for most instruments (price is
# quoted per share/barrel/point, lot = that many units) -- except MCX's
# Mini bullion contracts, which quote price per a DIFFERENT unit than the
# lot itself: GOLDM quotes ₹/10g but its lot is 100g (multiplier 10, not
# 100); SILVERM quotes ₹/kg but its lot is 5kg (multiplier 5, not 5000).
LOT_SIZE = {
    # NSE index derivatives
    'NIFTY': 65, 'BANKNIFTY': 30, 'FINNIFTY': 60, 'MIDCPNIFTY': 120,
    'NIFTYNXT50': 25, 'SENSEX': 20, 'BANKEX': 15, 'SENSSX': 20,
    'SENSEX75000': 20, 'BANK': 30, 'N': 65,
    # MCX commodities (multiplier = lot size / price-quotation unit)
    'CRUDEOIL': 100, 'CRUDE': 100, 'NATURALGAS': 1250, 'NATGAS': 1250,
    'NAT': 1250, 'GOLDM': 10, 'GOLD': 100, 'GOLDPETAL': 1,
    'SILVERM': 5, 'SILVER': 30, 'SILVERMIC': 1, 'COPPER': 1000, 'OIL': 1400,
    'ZINC': 5000, 'ALUMINIUM': 5000, 'ALUMINUM': 5000, 'LEAD': 5000,
    'NICKEL': 1500, 'COTTON': 25, 'GUARSEED': 5000,
    # NSE stock F&O
    'RELIANCE': 500, 'INFY': 400, 'ICICIBANK': 700, 'ICICI': 700, 'ONGC': 2250,
    'NTPC': 1500, 'DIVISLAB': 100, 'CDSL': 475, 'DMART': 150, 'DLF': 950,
    'APLAPOLLO': 350, 'GODREJCP': 500, 'DIXON': 50, 'ABB': 125,
    'GLENMARK': 375, 'WIPRO': 3000, 'TCS': 225, 'HDFCBANK': 650,
    'SBIN': 750, 'SBI': 750, 'AXISBANK': 625, 'MARUTI': 50, 'SUZLON': 12700,
    'VEDL': 1150, 'CUMMINSIND': 200, 'TATAPOWER': 1450, 'BIOCON': 2500,
    'HINDUNILVR': 300, 'EICHERMOT': 100, 'ADANIENT': 309, 'BAJFINANCE': 750,
    'SOLARINDS': 50, 'SOLARIND': 50, 'PREMIERENE': 650, 'PAYTM': 100,
    'KAYNES': 125, 'BHARATFORG': 500, 'TRENT': 200, 'SIEMENS': 125,
    'CHOLAFIN': 500, 'CHOLA': 500, 'LODHA': 450, 'ICICIGI': 500, 'MCX': 200,
    'BEL': 2850, 'BSE': 375, 'COLPAL': 175, 'HAL': 150, 'HCLTECH': 350,
    'IDEA': 80000, 'INDUSTOWER': 1700, 'IOC': 4875, 'IREDA': 2500,
    'LAURUSLABS': 850, 'M&M': 350, 'MOTHERSON': 6200, 'OFSS': 100,
    'PERSISTANT': 100, 'PNB': 4000, 'PRESTIGE': 400, 'RADICO': 200,
    'SHREECEM': 25, 'SONACOMS': 1000, 'TATASTEEL': 5500, 'TECH': 600,
}
DEFAULT_STOCK_LOT_SIZE = 100  # Stocks default lot size (100)


class Trade(models.Model):
    """One row of a channel's trade balance sheet (from ledger.xlsx)."""
    BUY_DIRECTIONS = {'BUY', 'CALL (UP)', 'LONG'}
    STATUS_CHOICES = [('Open', 'Open'), ('Closed', 'Closed')]
    ASSET_CHOICES = [
        ('stock', 'Stocks'), ('option', 'Options'), ('index', 'Index'),
        ('crypto', 'Crypto'), ('metal', 'Metals'), ('commodity', 'Oil & Commodities'),
        ('forex', 'Forex'), ('other', 'Other'),
    ]
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='trades')
    strike = models.FloatField(null=True, blank=True, help_text='Numeric strike price for options; null for non-options')
    asset_class = models.CharField(max_length=12, choices=ASSET_CHOICES,
                                   default='other', db_index=True)
    date = models.DateField(null=True, blank=True)
    trade = models.CharField(max_length=255, help_text="Instrument, e.g. 'NIFTY 23900 PE'")
    direction = models.CharField(max_length=32, blank=True)   # CALL (up) / PUT (down) / …
    entry = models.FloatField(null=True, blank=True)
    target = models.FloatField(null=True, blank=True)
    stop_loss = models.FloatField(null=True, blank=True)
    ltp_exit = models.FloatField(null=True, blank=True)       # LTP or exit price
    unrealized = models.FloatField(null=True, blank=True)     # Unreal ₹
    realized = models.FloatField(null=True, blank=True)       # P/L ₹ (realized)
    peak_profit = models.FloatField(null=True, blank=True)    # running max reported profit (trailing)
    cumulative = models.FloatField(null=True, blank=True)     # Cumulative ₹
    status = models.CharField(max_length=8, choices=STATUS_CHOICES, default='Open')
    note = models.TextField(blank=True)
    posted_at = models.DateTimeField(null=True, blank=True,
                                     help_text="Timestamp of the Telegram message that announced this trade")
    source_mid = models.BigIntegerField(null=True, blank=True,
                                        help_text="Telegram message id this trade was parsed from")
    manually_edited = models.BooleanField(default=False,
        help_text="Set automatically when an admin edits this row inline -- "
                  "mark_live/close_eod refuse to touch it after that, so a "
                  "manual correction sticks instead of getting overwritten "
                  "by the next automated pass.")

    objects = TradeQuerySet.as_manager()

    class Meta:
        ordering = ['date', 'id']
        constraints = [
            models.UniqueConstraint(fields=['channel', 'date', 'trade', 'entry', 'status'],
                                    name='uniq_trade_row'),
        ]

    def __str__(self):
        return f"{self.channel.short or self.channel.name}: {self.trade} ({self.status})"

    @property
    def root_symbol(self):
        """Leading ticker/index token, e.g. 'TATAMOTORS 1200 CE' -> 'TATAMOTORS'."""
        return (self.trade or '').split()[0].upper() if self.trade else ''

    @property
    def claimed_pct(self):
        """Consumer's own claimed return % on this trade (realized / entry)."""
        if self.realized is not None and self.entry:
            return round(100 * self.realized / self.entry, 2)
        return None

    @property
    def pl_tag(self):
        """'PROFIT'/'LOSS' derived from realized -- a property (not a
        stored column) so it can never drift out of sync with realized
        itself; served from the backend via TradeSerializer instead of
        being recomputed in the frontend."""
        if self.realized is None:
            return None
        return 'PROFIT' if self.realized >= 0 else 'LOSS'

    @property
    def lot_size(self):
        """Exchange P&L multiplier for this instrument (see LOT_SIZE above).
        For stocks, defaults to 100 (DEFAULT_STOCK_LOT_SIZE).
        For known derivatives and stocks in LOT_SIZE, returns their specific lot size.
        For unmapped options, returns 1."""
        root = self.root_symbol
        if root in LOT_SIZE:
            return LOT_SIZE[root]
        return 1 if self.asset_class == 'option' else DEFAULT_STOCK_LOT_SIZE

    @property
    def realized_total(self):
        """realized (raw per-unit price diff, the source of truth kept for
        win-rate/trust-tier math elsewhere) scaled to real money by
        lot_size. None whenever realized itself is None -- never fabricates
        a total off an unpriced trade."""
        if self.realized is None:
            return None
        return round(self.realized * self.lot_size, 2)

    # Live-price close is skipped past this entry/price ratio (either
    # direction): guards against comparing the wrong instrument's price --
    # an option's underlying spot vs. its premium (two different scales,
    # e.g. NIFTY spot ~23000 vs. a ~200 premium), or a pre-existing parse
    # artifact where entry/stop_loss/target were misread and don't reflect
    # the instrument's real price scale at all (observed: a stock trade
    # with entry=24 against a live price of 12231). Either way, a jump this
    # large from a channel-posted level means the data can't be trusted for
    # an automatic close and needs a human look, not a silent action.
    LIVE_PRICE_SANITY_RATIO = 5.0

    def mark_live(self, price):
        """Close this Open trade if live price has crossed its own posted
        stop-loss or target level -- a follow-on for calls the channel never
        posted an explicit exit/SL-hit message for. Uses the channel's own
        absolute levels (not a percentage rule, unlike PaperTrade.mark),
        since that's what was actually posted. Returns True if closed.

        Options are skipped outright: there's no cheap live options-chain
        price source here, and the underlying's spot price is not the
        option's premium -- comparing them is meaningless, not just noisy.
        Detected by trade-string shape (option_strike()), not just
        asset_class -- some CE/PE rows are mistagged as 'other' upstream,
        and asset_class alone would let those through to a nonsense
        spot-vs-premium comparison."""
        if self.manually_edited:
            return False
        if self.status != 'Open' or price is None or self.entry is None:
            return False
        if self.asset_class == 'option' or self.option_strike():
            return False
        if price <= 0 or self.entry <= 0:
            return False
        ratio = price / self.entry
        if ratio > self.LIVE_PRICE_SANITY_RATIO or ratio < (1.0 / self.LIVE_PRICE_SANITY_RATIO):
            return False
        is_buy = (self.direction or '').upper() in self.BUY_DIRECTIONS
        # Structural sanity: for a BUY, stop_loss must sit below entry and
        # target above it (the reverse for a SELL/PUT) -- a call posted as
        # "SL 400 / target 950 points from entry" on a BUY at 49500 stores
        # nonsense in these absolute-level fields (observed live), and a
        # target on the wrong side of entry would otherwise "hit" on the
        # very first price check regardless of where the price actually is.
        if is_buy:
            if self.stop_loss is not None and self.stop_loss >= self.entry:
                return False
            if self.target is not None and self.target <= self.entry:
                return False
        else:
            if self.stop_loss is not None and self.stop_loss <= self.entry:
                return False
            if self.target is not None and self.target >= self.entry:
                return False
        reason = None
        if is_buy:
            if self.stop_loss is not None and price <= self.stop_loss:
                reason = 'stop-loss'
            elif self.target is not None and price >= self.target:
                reason = 'target'
        else:
            if self.stop_loss is not None and price >= self.stop_loss:
                reason = 'stop-loss'
            elif self.target is not None and price <= self.target:
                reason = 'target'
        if reason is None:
            return False
        realized = round((price - self.entry) if is_buy else (self.entry - price), 2)
        # Another row may already occupy this (channel, date, trade, entry,
        # Closed) slot -- e.g. a duplicate re-posted signal the channel
        # itself already closed. Merge into that twin instead of violating
        # uniq_trade_row (same pattern as parse_signals.book()/close_at_price()).
        dup = Trade.objects.filter(channel=self.channel, date=self.date, trade=self.trade,
                                   entry=self.entry, status='Closed').exclude(pk=self.pk).first()
        if dup:
            if dup.realized is None or realized > dup.realized:
                dup.realized = realized
                dup.ltp_exit = price
                dup.save(update_fields=['realized', 'ltp_exit'])
            self.delete()
            self._emit_close_event(dup, reason, price)
            return True
        self.ltp_exit = price
        self.realized = realized
        self.status = 'Closed'
        self.note = (self.note + f' [auto-closed:{reason}@live {price}]').strip()
        self.save(update_fields=['status', 'ltp_exit', 'realized', 'note'])
        self._emit_close_event(self, reason, price)
        return True

    def _emit_close_event(self, surviving_row, reason, price):
        """Record a user-facing Event for this auto-close -- the frontend
        polls these to turn the live-sync heartbeat into an actual
        notification instead of just a "data is fresh" pulse."""
        name = surviving_row.channel.short or surviving_row.channel.name
        Event.objects.create(
            kind='target_hit' if reason == 'target' else 'stop_loss_hit',
            trade=surviving_row, channel=surviving_row.channel,
            message=f'{name}: {surviving_row.trade} hit {reason} @ {price}')

    _OPTION_RE = re.compile(r'^\S+\s+(\d+(?:\.\d+)?)\s*(CE|PE)\b', re.IGNORECASE)

    def option_strike(self):
        """Parse ('AXISBANK 1300 CE' -> (1300.0, 'CE')) or None if the
        trade string doesn't match the usual '<symbol> <strike> <CE|PE>'
        shape."""
        m = self._OPTION_RE.match((self.trade or '').strip())
        if not m:
            return None
        return float(m.group(1)), m.group(2).upper()

    def close_eod(self, price):
        """Force-close an intraday call that never hit its posted SL/target
        by end of the same trading day -- these are day calls, not swing
        positions, so an Open row that outlives its own posting day is a
        stale position, not a real one. `price` may be None (no live quote
        available at close): still closes the row, just marked as
        unpriced (realized left null) rather than silently rolling it to
        the next day, since a channel-call tracker with no EOD square-off
        is exactly how "91 open" backlogs accumulate."""
        if self.manually_edited:
            return False
        if self.status != 'Open':
            return False
        # Options: `price` from the caller is the underlying's spot, not
        # the option's own premium -- comparing them directly is
        # meaningless (mark_live's reasoning too). There's no live
        # options-chain source here, so the best available EOD estimate is
        # intrinsic value (max(spot-strike,0) for a call, the mirror for a
        # put) against the strike parsed out of the trade string -- a real,
        # standard approximation, but NOT the option's actual closing
        # premium (it ignores time value entirely). Always flagged as an
        # estimate in the note/event so it's never mistaken for an
        # observed price.
        is_estimate = False
        # Detected by trade-string shape, not just asset_class == 'option'
        # -- some CE/PE rows arrive mistagged as 'other' upstream, and
        # asset_class alone would let those fall through to a meaningless
        # spot-vs-premium comparison below instead of the intrinsic-value
        # estimate.
        looks_like_option = self.asset_class == 'option' or bool(self.option_strike())
        if looks_like_option:
            parsed = self.option_strike()
            is_commodity_or_metal = self.asset_class in ('commodity', 'metal') or any(
                c in (self.trade or '').upper() for c in ['CRUDE', 'OIL', 'NATURALGAS', 'NATGAS', 'GOLD', 'SILVER', 'COPPER', 'ZINC', 'ALUMINUM', 'ALUMINIUM'])
            if parsed and price is not None and price > 0 and not is_commodity_or_metal:
                strike, opt_type = parsed
                if 'SENSEX' in (self.trade or '').upper() and strike < 40000:
                    price = None
                elif 'NIFTY' in (self.trade or '').upper() and (strike < 10000 or strike > 40000):
                    price = None
                else:
                    price = round(max(price - strike, 0) if opt_type == 'CE' else max(strike - price, 0), 2)
                    is_estimate = True
            else:
                price = None
        # Same sanity ratio mark_live uses: catches unit mismatches (e.g.
        # an MCX gold call posted in INR/10g vs a fetched USD/troy-oz
        # quote). Skipped for the option-intrinsic estimate above -- a
        # deep-ITM move can legitimately be many multiples of the original
        # premium, that's not a unit-mismatch signal there.
        if price is not None and self.entry and not is_estimate:
            ratio = price / self.entry
            if ratio > self.LIVE_PRICE_SANITY_RATIO or ratio < (1.0 / self.LIVE_PRICE_SANITY_RATIO):
                price = None
        is_buy = (self.direction or '').upper() in self.BUY_DIRECTIONS
        # >= 0, not > 0: an option's estimated intrinsic value can be a
        # real, legitimate zero (worthless at close) -- that's a real
        # data point (lost the full premium), not a "missing price".
        realized = None
        if price is not None and price >= 0 and self.entry is not None and self.entry > 0:
            if looks_like_option:
                realized = round(price - self.entry, 2)
            else:
                realized = round((price - self.entry) if is_buy else (self.entry - price), 2)
        dup = Trade.objects.filter(channel=self.channel, date=self.date, trade=self.trade,
                                   entry=self.entry, status='Closed').exclude(pk=self.pk).first()
        if dup:
            if realized is not None and (dup.realized is None or realized > dup.realized):
                dup.realized = realized
                dup.ltp_exit = price
                dup.save(update_fields=['realized', 'ltp_exit'])
            self.delete()
            surviving = dup
        else:
            self.ltp_exit = price
            self.realized = realized
            self.status = 'Closed'
            tag = f'[eod-closed:estimated intrinsic value @ {price}]' if is_estimate \
                else f' [eod-closed@{price if price is not None else "no quote"}]'
            self.note = (self.note + ' ' + tag).strip()
            self.save(update_fields=['status', 'ltp_exit', 'realized', 'note'])
            surviving = self
        name = surviving.channel.short or surviving.channel.name
        if is_estimate:
            detail = f' (est. intrinsic value @ {price}, not a real quoted premium)'
        elif price is not None:
            detail = f' @ {price}'
        else:
            detail = ' (no live quote)'
        Event.objects.create(
            kind='eod_close', trade=surviving, channel=surviving.channel,
            message=f'{name}: {surviving.trade} squared off at close' + detail)
        return True


class Event(models.Model):
    """A user-facing, notifiable occurrence (trade auto-closed against its
    own posted target/stop-loss) -- distinct from core.JobRun/HealthIssue,
    which are admin-only ops signals. The frontend polls
    GET /api/tracker/events/?since=<id> on the same cadence as the
    live-sync heartbeat, so "live" actually surfaces something instead of
    only updating numbers silently in the background.
    """
    KIND_CHOICES = [
        ('target_hit', 'Target hit'),
        ('stop_loss_hit', 'Stop-loss hit'),
        ('eod_close', 'Squared off at close'),
    ]
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    trade = models.ForeignKey(Trade, null=True, blank=True, on_delete=models.SET_NULL, related_name='events')
    channel = models.ForeignKey(Channel, null=True, blank=True, on_delete=models.SET_NULL)
    message = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return self.message


class ProcessedProfitEvent(models.Model):
    """Marks a TelegramMessage as already considered for profit-booking /
    exit-price closing by parse_signals, regardless of whether it actually
    found a trade to close.

    Why this exists: parse_signals replays the full message history in
    chronological order every run, creating Trade rows lazily as their entry
    message is reached. A profit/exit message whose OWN timestamp precedes
    its target trade's entry message (a real, observed data pattern -- e.g.
    a stale "booked @ price" post about an earlier, already-closed position)
    correctly finds no candidate on a run that starts from an empty Trade
    table. But if the Trade table isn't cleared between runs (the normal way
    this command is actually re-run -- see docs/AGENT_HANDOFF.md §7), a
    later run finds that some *other*, unrelated trade created later in the
    replay now happens to be sitting Open, and wrongly attaches the stale
    message's profit/price to it. Recording every considered message here --
    on a miss as well as a hit -- makes a second run skip it outright instead
    of re-evaluating it against a Trade table that has since changed."""
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='+')
    mid = models.BigIntegerField(help_text="Telegram message id")
    kind = models.CharField(max_length=16, choices=[('profit', 'Profit'),
                                                     ('exit_price', 'Exit price'),
                                                     ('llm_triage', 'LLM triage')])

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['channel', 'mid', 'kind'],
                                    name='uniq_processed_profit_event'),
        ]


class UserPreference(models.Model):
    """Per-user paper-trading preferences (requirement 2/3)."""
    user = models.OneToOneField('auth.User', on_delete=models.CASCADE,
                                related_name='prefs')
    auto_paper = models.BooleanField(
        default=True, help_text="Auto-open paper trades from consumer signals")
    capital_per_trade = models.PositiveIntegerField(default=10000,
        help_text="Fixed ₹ notional per paper trade")
    stop_loss_pct = models.FloatField(default=20.0)
    trailing_pct = models.FloatField(default=20.0)
    profit_target_pct = models.FloatField(default=50.0,
        help_text="Close a paper trade outright once unrealized profit reaches this %")
    max_hold_days = models.PositiveIntegerField(default=60,
        help_text="Force-close a paper trade after this many days, regardless of price")
    auto_consumers = models.ManyToManyField(
        Channel, blank=True, related_name='auto_pref_users',
        help_text="Consumers whose signals auto-open paper trades (top-10 default)")

    def __str__(self):
        return f"prefs:{self.user.username}"

    @classmethod
    def for_user(cls, user):
        pref, _ = cls.objects.get_or_create(user=user)
        return pref


class PaperTradeQuerySet(models.QuerySet):
    def open(self):
        return self.filter(status='Open')

    def closed(self):
        return self.filter(status='Closed')

    def channel_accuracy(self, user=None):
        """Per-consumer accuracy: does the consumer's claim match market reality?

        Returns rows ranked by hit-rate (share of validated trades where the
        consumer's claimed profit direction agreed with the paper trade's
        real-market outcome), plus avg |claimed − market| gap.
        """
        qs = self.filter(status='Closed', accuracy__isnull=False,
                         source_trade__isnull=False)
        if user is not None:
            qs = qs.filter(user=user)
        rows = (qs.order_by().values('source_trade__channel',
                                     'source_trade__channel__name',
                                     'source_trade__channel__short')
                .annotate(
                    validated=Count('id'),
                ))
        out = []
        for r in rows:
            sub = qs.filter(source_trade__channel=r['source_trade__channel'])
            hits = sum(1 for x in sub if x.accuracy == 1.0)
            gaps = [abs((x.consumer_claimed_pct or 0) - (x.realized_pct or 0))
                    for x in sub if x.consumer_claimed_pct is not None]
            hit_rate = round(100 * hits / r['validated'], 1) if r['validated'] else None
            tier = trust_tier(hit_rate, r['validated'])
            out.append({
                'channel': r['source_trade__channel'],
                'name': r['source_trade__channel__name'],
                'short': r['source_trade__channel__short'],
                'validated': r['validated'],
                'hit_rate': hit_rate,
                'confidence_score': wilson_lower_bound(hits, r['validated']),
                'avg_gap_pct': round(sum(gaps) / len(gaps), 1) if gaps else None,
                'tier': tier,
                'tier_label': TIER_LABELS.get(tier),
            })
        out.sort(key=lambda x: (x['hit_rate'] or -1, x['validated']), reverse=True)
        return out


class PaperTrade(models.Model):
    """A simulated position opened at REAL market price (not the consumer's
    posted price), validated against live market with SL + trailing stop."""
    STATUS_CHOICES = [('Open', 'Open'), ('Closed', 'Closed')]
    SIDE_CHOICES = [('BUY', 'Buy'), ('SELL', 'Sell')]
    SOURCE_CHOICES = [('yahoo', 'Yahoo'), ('dhan', 'Dhan'),
                      ('posted', 'Consumer posted'), ('manual', 'Manual')]
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE,
                             related_name='paper_trades')
    symbol = models.CharField(max_length=64)
    asset_class = models.CharField(max_length=12, choices=Trade.ASSET_CHOICES,
                                   default='stock')
    side = models.CharField(max_length=4, choices=SIDE_CHOICES, default='BUY')
    notional_inr = models.PositiveIntegerField(default=10000)
    entry_price = models.FloatField()
    price_source = models.CharField(max_length=8, choices=SOURCE_CHOICES,
                                    default='posted', blank=True)
    current_price = models.FloatField(null=True, blank=True)
    highest_price = models.FloatField(null=True, blank=True)
    lowest_price = models.FloatField(null=True, blank=True)
    stop_loss_pct = models.FloatField(default=20.0)
    trailing_pct = models.FloatField(default=20.0)
    profit_target_pct = models.FloatField(default=50.0,
        help_text="Close outright once unrealized profit reaches this %")
    max_hold_days = models.PositiveIntegerField(default=60,
        help_text="Force-close after this many days, regardless of price")
    status = models.CharField(max_length=8, choices=STATUS_CHOICES,
                              default='Open', db_index=True)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    exit_price = models.FloatField(null=True, blank=True)
    realized_pct = models.FloatField(null=True, blank=True)
    realized_inr = models.FloatField(null=True, blank=True)
    source_trade = models.ForeignKey(Trade, null=True, blank=True,
                                     on_delete=models.SET_NULL,
                                     related_name='paper_trades')
    consumer_claimed_pct = models.FloatField(null=True, blank=True)
    accuracy = models.FloatField(null=True, blank=True,
        help_text="1.0 if consumer's claimed direction matched market outcome")
    is_manual = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    objects = PaperTradeQuerySet.as_manager()

    class Meta:
        ordering = ['-opened_at']

    def __str__(self):
        return f"{self.user.username}:{self.side} {self.symbol} @ {self.entry_price}"

    # ---- engine (fat model) ------------------------------------------------
    def _pct(self, price):
        if not price or not self.entry_price:
            return 0.0
        move = (price - self.entry_price) / self.entry_price
        if self.side == 'SELL':
            move = -move
        return move * 100

    def unrealized_pct(self, price=None):
        return round(self._pct(price if price is not None else (self.current_price or self.entry_price)), 2)

    def unrealized_inr(self, price=None):
        return round(self.notional_inr * self.unrealized_pct(price) / 100.0, 2)

    def _max_hold_exceeded(self, now):
        return bool(self.max_hold_days) and (now - self.opened_at).days >= self.max_hold_days

    def mark(self, price, now=None):
        """Update to market price; close on max hold age, SL hit, profit
        target reached, or trailing drawdown, in that priority order (the
        hard time deadline overrides everything else -- "no matter what" --
        then cap the loss, then lock in a win that already cleared the
        target, then let a smaller win ride until it pulls back from peak).
        Returns True if the trade was closed by this mark.

        The max-hold deadline is enforced even with no fresh quote (price=
        None), using the last known price, so a delisted/illiquid symbol
        can't sit open forever just because live pricing stopped working."""
        from django.utils import timezone as tz
        now = now or tz.now()
        if price is None:
            if self._max_hold_exceeded(now):
                self._close(self.current_price or self.entry_price, now, 'max-hold')
                return True
            return False
        self.current_price = price
        self.highest_price = max(self.highest_price or price, price)
        self.lowest_price = min(self.lowest_price or price, price)
        pct = self._pct(price)
        closed = False
        reason = None
        if self._max_hold_exceeded(now):
            closed, reason = True, 'max-hold'
        elif pct <= -abs(self.stop_loss_pct):
            closed, reason = True, 'stop-loss'
        elif self.profit_target_pct and pct >= abs(self.profit_target_pct):
            closed, reason = True, 'profit-target'
        elif self.trailing_pct and self._trail_hit():
            closed, reason = True, 'trailing'
        if closed:
            self._close(price, now, reason)
        else:
            self.save(update_fields=['current_price', 'highest_price', 'lowest_price'])
        return closed

    def _trail_hit(self):
        # trailing only arms once the position is in profit
        if self.side == 'BUY':
            peak = self.highest_price or self.entry_price
            if peak <= self.entry_price:
                return False
            return self.current_price <= peak * (1 - self.trailing_pct / 100.0)
        peak = self.lowest_price or self.entry_price
        if peak >= self.entry_price:
            return False
        return self.current_price >= peak * (1 + self.trailing_pct / 100.0)

    def _close(self, price, now, reason):
        self.status = 'Closed'
        self.closed_at = now
        self.exit_price = price
        self.realized_pct = round(self._pct(price), 2)
        self.realized_inr = round(self.notional_inr * self.realized_pct / 100.0, 2)
        if self.consumer_claimed_pct is not None:
            self.accuracy = 1.0 if (self.consumer_claimed_pct > 0) == (self.realized_pct > 0) else 0.0
        self.notes = (self.notes + f' [closed:{reason}]').strip()
        self.save(update_fields=['status', 'closed_at', 'exit_price',
                                 'realized_pct', 'realized_inr', 'accuracy', 'notes'])

    def close(self, price, now=None):
        from django.utils import timezone as tz
        self._close(price, now or tz.now(), 'manual')

    @classmethod
    def open_for_user(cls, user, symbol, asset_class, side, price, source='posted',
                      source_trade=None, notional=None, consumer_claimed_pct=None):
        pref = UserPreference.for_user(user)
        notional = notional or pref.capital_per_trade
        return cls.objects.create(
            user=user, symbol=symbol.upper(), asset_class=asset_class,
            side=side, notional_inr=notional, entry_price=price,
            price_source=source, current_price=price,
            highest_price=price, lowest_price=price,
            stop_loss_pct=pref.stop_loss_pct, trailing_pct=pref.trailing_pct,
            profit_target_pct=pref.profit_target_pct, max_hold_days=pref.max_hold_days,
            source_trade=source_trade, consumer_claimed_pct=consumer_claimed_pct)


class Quote(models.Model):
    """Latest market quote per (channel, symbol) from market.json."""
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='quotes')
    symbol = models.CharField(max_length=64)
    name = models.CharField(max_length=128, blank=True)
    kind = models.CharField(max_length=16, blank=True)   # LTP / OPT
    ltp = models.FloatField(null=True, blank=True)
    asof = models.DateTimeField(null=True, blank=True,
                                help_text="When this quote was fetched from the market provider")

    class Meta:
        ordering = ['symbol']
        constraints = [
            models.UniqueConstraint(fields=['channel', 'symbol'], name='uniq_quote'),
        ]


class QuantityRule(models.Model):
    """Position-size rules from quantities.json (lot sizes / qty multipliers)."""
    SCOPE_CHOICES = [('default', 'Default'), ('symbol', 'By symbol'), ('group', 'By group')]
    scope = models.CharField(max_length=8, choices=SCOPE_CHOICES)
    key = models.CharField(max_length=64, blank=True, help_text="Symbol or peer id (empty for default)")
    qty = models.IntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['scope', 'key'], name='uniq_qty_rule'),
        ]


class Watchlist(models.Model):
    """A user's followed channels, so the frontend can build a
    'my channels' filter over the leaderboard/feed."""
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE,
                             related_name='watchlist')
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE,
                                related_name='followers')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'channel'], name='uniq_watchlist'),
        ]

    def __str__(self):
        return f"{self.user.username} follows {self.channel.short or self.channel.name}"


class TelegramMessage(models.Model):
    """Raw scraped message from a tracked channel (poller ledger)."""
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='messages')
    mid = models.BigIntegerField(help_text="Telegram message id")
    day_label = models.CharField(max_length=32, blank=True)   # e.g. 'Sunday'
    text = models.TextField()
    ts = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-ts']
        constraints = [
            models.UniqueConstraint(fields=['channel', 'mid'], name='uniq_message'),
        ]
