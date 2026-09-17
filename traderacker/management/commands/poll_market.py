"""Poll live market prices and mark all open paper trades (requirement 6),
plus auto-close open channel-call trades against their own posted SL/target.

A SEPARATE job from parse_signals/paper_autotrade: when a paper trade exists,
this goes to the market, fetches the real price, and applies the master
close rules (stop-loss / profit-target / trailing / max-hold), all
per-user configurable via UserPreference. A symbol whose quote can't be
fetched still gets its max-hold deadline enforced (no matter what) using
its last known price -- only price-dependent closes (SL/target/trailing)
are skipped without a fresh quote.

Channel-call trades (the main signal tracker, not paper trading) only close
when the channel itself posts a follow-up message -- if it never does, an
SL/target that was actually hit in the real market sits "Open" forever. This
same poll also fetches live prices for those and closes them against the
channel's own posted absolute stop-loss/target levels (Trade.mark_live) --
distinct from PaperTrade's percentage-based rules, since these are prices the
channel itself stated.

  manage.py poll_market [--user USERNAME]
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db.models import Q

from traderacker import market
from traderacker.models import PaperTrade, Trade


class Command(BaseCommand):
    help = ('Fetch live prices and apply the master close rules to open paper trades, '
            'and auto-close open channel-call trades against their posted SL/target.')

    def add_arguments(self, parser):
        parser.add_argument('--user', default=None)

    def handle(self, *args, **opts):
        qs = PaperTrade.objects.open().select_related('user')
        if opts['user']:
            qs = qs.filter(user__username=opts['user'])

        priced = closed = errors = no_quote = 0
        for pt in qs:
            price, _src = market.get_price(pt.symbol, pt.asset_class)
            try:
                if price is None:
                    no_quote += 1
                    if pt.mark(None):   # still enforces max-hold, no matter what
                        closed += 1
                    continue
                priced += 1
                if pt.mark(price):
                    closed += 1
            except Exception as exc:
                # One bad row (e.g. a duplicate-key race with a concurrent
                # run) must not abort the whole batch -- log and keep going.
                errors += 1
                self.stderr.write(self.style.WARNING(f'paper trade {pt.id} mark failed: {exc}'))
        if errors:
            self.stdout.write(self.style.WARNING(f'Paper trades: {errors} error(s), see above'))
        self.stdout.write(self.style.SUCCESS(
            f'Paper trades marked: {priced} priced · {closed} closed · {no_quote} no-quote'))

        t_priced, t_closed, t_no_quote = self._mark_channel_trades()
        self.stdout.write(self.style.SUCCESS(
            f'Channel-call trades marked: {t_priced} priced · '
            f'{t_closed} closed (SL/target) · {t_no_quote} no-quote'))

    def _mark_channel_trades(self):
        qs = Trade.objects.filter(status='Open').exclude(asset_class='option').filter(
            Q(stop_loss__isnull=False) | Q(target__isnull=False))
        price_cache = {}
        priced = closed = no_quote = 0
        for t in qs:
            cache_key = (t.root_symbol, t.asset_class)
            if cache_key not in price_cache:
                price_cache[cache_key], _src = market.get_price(t.root_symbol, t.asset_class)
            price = price_cache[cache_key]
            if price is None:
                no_quote += 1
                continue
            priced += 1
            try:
                if t.mark_live(price):
                    closed += 1
            except Exception as exc:
                # One bad row (e.g. a duplicate-key race with a concurrent
                # run) must not abort the whole batch -- log and keep going.
                self.stderr.write(self.style.WARNING(f'trade {t.id} mark_live failed: {exc}'))
        return priced, closed, no_quote
