from datetime import date as _date

from django.db import models
from django.db.models import Count, Q, Sum


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
    return 'watch'


TIER_LABELS = {
    'top': 'Top tier', 'solid': 'Solid', 'watch': 'Watch', 'building': 'Building track record',
}


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

    def picks(self, limit=25):
        """Cross-channel consensus: per normalized symbol, BUY vs SELL counts.

        'buy' = channels leaning long (BUY / CALL(up)); 'sell' = channels
        leaning short (SELL / PUT(down)). A symbol is one recommendation per
        channel (distinct) so a single noisy channel can't dominate.
        """
        from django.db.models.functions import Upper
        rows = (self.exclude(entry=None)
                .annotate(sym=Upper('trade'))
                .values('sym')
                .annotate(
                    buy=Count('id', filter=Q(direction__in=['BUY', 'CALL (up)'])),
                    sell=Count('id', filter=Q(direction__in=['SELL', 'PUT (down)'])),
                    buyers=Count('channel', distinct=True,
                                 filter=Q(direction__in=['BUY', 'CALL (up)'])),
                    sellers=Count('channel', distinct=True,
                                  filter=Q(direction__in=['SELL', 'PUT (down)'])),
                )
                .order_by('-buy'))
        out = []
        for r in rows:
            sym = r['sym'].split()[0] if r['sym'] else ''
            out.append({'symbol': sym, 'buy': r['buy'], 'sell': r['sell'],
                        'buyers': r['buyers'], 'sellers': r['sellers'],
                        'net': r['buy'] - r['sell']})
        # collapse duplicate root symbols (e.g. NIFTY 24000 CE + NIFTY 25000 PE → NIFTY)
        merged = {}
        for o in out:
            m = merged.setdefault(o['symbol'], {'symbol': o['symbol'], 'buy': 0,
                                                'sell': 0, 'buyers': 0, 'sellers': 0})
            m['buy'] += o['buy']; m['sell'] += o['sell']
            m['buyers'] = max(m['buyers'], o['buyers'])
            m['sellers'] = max(m['sellers'], o['sellers'])
        result = sorted(merged.values(),
                        key=lambda x: (x['buy'] + x['sell']), reverse=True)
        for x in result:
            x['net'] = x['buy'] - x['sell']
        return result[:limit]

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
            o['tier'] = trust_tier(o['success_rate'], o['booked'])
        return out


class Trade(models.Model):
    """One row of a channel's trade balance sheet (from ledger.xlsx)."""
    STATUS_CHOICES = [('Open', 'Open'), ('Closed', 'Closed')]
    ASSET_CHOICES = [
        ('stock', 'Stocks'), ('option', 'Options'), ('index', 'Index'),
        ('crypto', 'Crypto'), ('metal', 'Metals'), ('commodity', 'Oil & Commodities'),
        ('forex', 'Forex'), ('other', 'Other'),
    ]
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='trades')
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
            out.append({
                'channel': r['source_trade__channel'],
                'name': r['source_trade__channel__name'],
                'short': r['source_trade__channel__short'],
                'validated': r['validated'],
                'hit_rate': hit_rate,
                'avg_gap_pct': round(sum(gaps) / len(gaps), 1) if gaps else None,
                'tier': trust_tier(hit_rate, r['validated']),
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

    def mark(self, price, now=None):
        """Update to market price; close on SL or trailing drawdown.
        Returns True if the trade was closed by this mark."""
        from django.utils import timezone as tz
        if price is None:
            return False
        now = now or tz.now()
        self.current_price = price
        self.highest_price = max(self.highest_price or price, price)
        self.lowest_price = min(self.lowest_price or price, price)
        pct = self._pct(price)
        closed = False
        reason = None
        if pct <= -abs(self.stop_loss_pct):
            closed, reason = True, 'stop-loss'
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
            source_trade=source_trade, consumer_claimed_pct=consumer_claimed_pct)


class Quote(models.Model):
    """Latest market quote per (channel, symbol) from market.json."""
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name='quotes')
    symbol = models.CharField(max_length=64)
    name = models.CharField(max_length=128, blank=True)
    kind = models.CharField(max_length=16, blank=True)   # LTP / OPT
    ltp = models.FloatField(null=True, blank=True)
    asof = models.CharField(max_length=64, blank=True)

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
