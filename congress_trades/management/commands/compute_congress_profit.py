"""Compute (or refresh) the estimated profit fields on CongressTrade rows.

Run after import_congress_trades to fill in realized_profit / unrealized_profit
/ profit_kind / matched_trade for every buy/sell row, FIFO-matched per
politician+ticker and priced off real market data (see congress_trades.market
for the approximation this relies on -- disclosures give a dollar range, not
an exact price, so this is always an estimate).

  manage.py compute_congress_profit [--verbose]

Safe to re-run: it recomputes from scratch each time (a newly-imported sale
can retroactively close a previously-'open' buy), so run it again after each
import_congress_trades.
"""
from django.core.management.base import BaseCommand

from congress_trades.models import CongressTrade


class Command(BaseCommand):
    help = "Compute estimated realized/unrealized profit for Congress trade disclosures."

    def add_arguments(self, parser):
        parser.add_argument('--verbose', action='store_true', help='Print progress per politician+ticker group.')

    def handle(self, *args, **opts):
        verbose = opts['verbose']

        def progress(i, total, politician, ticker):
            if verbose and (i % 25 == 0 or i == total - 1):
                self.stdout.write(f"  [{i+1}/{total}] {politician} · {ticker}")

        self.stdout.write("Computing profit estimates (FIFO-matching buys/sells, pricing off Yahoo)...")
        n = CongressTrade.objects.compute_profit_estimates(progress=progress if verbose else None)
        self.stdout.write(self.style.SUCCESS(f"Done. {n} rows updated with a profit estimate."))

        realized = CongressTrade.objects.filter(profit_kind='realized', transaction_type='buy').count()
        unrealized = CongressTrade.objects.filter(profit_kind='unrealized').count()
        unpriced_open = CongressTrade.objects.filter(
            transaction_type='buy', matched_trade__isnull=True, profit_kind='').count()
        self.stdout.write(f"Closed round-trips priced: {realized}")
        self.stdout.write(f"Open positions marked to market: {unrealized}")
        self.stdout.write(f"Open buys still unpriced (no historical price found): {unpriced_open}")
