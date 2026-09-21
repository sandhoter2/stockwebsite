"""Close the historical backlog of Open trades whose own day's close_eod()
never ran -- close_eod() only ever fires for trades dated TODAY, inside
poll_market's 3-minute pre-close window; a trade missed on its own day (cron
gap, downtime, or simply predating this job's existence) stays Open forever
with no way to ever close. Observed live: 10,109 of 13,279 trades (76%)
stuck Open, spanning 2022-02-08 to 2026-09-18 across 647 distinct dates.

Reuses Trade.close_eod() completely unchanged for the actual close/merge/
sanity-ratio/intrinsic-value logic -- the only new piece is sourcing each
trade's OWN DATE's real historical closing price (not today's live price,
which would misattribute days/years of drift to a single-day call) via
market.yahoo_historical_series(), cached per (root_symbol, asset_class) so
a symbol with hundreds of backlog trades costs one HTTP call, not hundreds.

Trades whose symbol has no resolvable historical data (delisted, garbled
ticker, pre-listing date, etc.) are still closed -- close_eod(None) leaves
realized/ltp_exit honestly NULL rather than fabricating a price, exactly
its existing behavior for a same-day trade with no live quote.

  manage.py close_stale_backlog [--dry-run] [--limit N]
"""
from django.core.management.base import BaseCommand

from traderacker import market
from traderacker.models import Trade


class Command(BaseCommand):
    help = "Close the historical Open-trade backlog using each trade's own date's real historical price."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would happen without writing anything.')
        parser.add_argument('--limit', type=int, default=None,
                            help='Cap the number of trades processed (for a bounded test run).')

    def handle(self, *args, **opts):
        dry_run = opts['dry_run']
        qs = Trade.objects.filter(status='Open', manually_edited=False).order_by('trade')
        if opts['limit']:
            qs = qs[:opts['limit']]
        trades = list(qs)
        self.stdout.write(f'{len(trades)} Open, non-manually-edited trades to process.')

        series_cache = {}
        priced = unpriced = closed = errors = 0
        for i, t in enumerate(trades, 1):
            cache_key = (t.root_symbol, t.asset_class)
            if cache_key not in series_cache:
                series_cache[cache_key] = market.yahoo_historical_series(t.root_symbol, t.asset_class)
            series = series_cache[cache_key]
            price = market.closest_close_on_or_before(series, t.date) if t.date else None
            if price is not None:
                priced += 1
            else:
                unpriced += 1
            if dry_run:
                continue
            try:
                if t.close_eod(price):
                    closed += 1
            except Exception as exc:
                errors += 1
                self.stderr.write(self.style.WARNING(f'trade {t.id} close_eod failed: {exc}'))
            if i % 500 == 0:
                self.stdout.write(f'...{i}/{len(trades)} processed ({len(series_cache)} symbols fetched)')

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'DRY RUN: {priced} would get a real historical price, {unpriced} would close unpriced.'))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Closed {closed} trade(s) ({priced} priced, {unpriced} unpriced) · {errors} error(s) · '
                f'{len(series_cache)} unique symbols fetched.'))
