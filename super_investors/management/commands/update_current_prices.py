"""Fetch and store a live current price per distinct ticker, so 13F holdings
(especially brand-new positions with no prior quarter to diff against) can
show a 'since filing' unrealized gain/loss instead of a bare "n/a".

13F filings only give a quarter-end market value, never a per-share trade
price, so `Holding.price_at_filing` (market_value / shares) is already an
approximation -- this command only supplies the OTHER side of that estimate
(today's price), reusing congress_trades.market.get_price rather than
building a second Yahoo-fetch helper (that module already resolves a bare
US ticker correctly, unlike traderacker.market's NSE-defaulting version).

  manage.py update_current_prices

Safe to re-run on a schedule (e.g. daily): updates current_price/
current_price_as_of on every Holding row sharing a resolved ticker. Rows
with no resolved ticker (~40 of the 60-ticker CUSIP map's misses) are
skipped -- there's nothing to price them against.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from congress_trades.market import get_price
from super_investors.models import Holding


class Command(BaseCommand):
    help = "Fetch and store a live current price per distinct ticker for super_investors Holdings."

    def handle(self, *args, **opts):
        tickers = list(
            Holding.objects.exclude(ticker='').values_list('ticker', flat=True).distinct())
        self.stdout.write(f"Pricing {len(tickers)} distinct tickers...")

        priced = failed = 0
        now = timezone.now()
        for i, ticker in enumerate(tickers):
            price, _source = get_price(ticker)
            if price is None:
                failed += 1
                continue
            updated = Holding.objects.filter(ticker=ticker).update(
                current_price=price, current_price_as_of=now)
            priced += 1
            if i % 20 == 0:
                self.stdout.write(f"  [{i+1}/{len(tickers)}] {ticker} -> {price} ({updated} rows)")

        self.stdout.write(self.style.SUCCESS(
            f"Done. {priced} tickers priced, {failed} failed (unresolved/no data)."))
