"""Poll live market prices and mark all open paper trades (requirement 6).

A SEPARATE job from parse_signals/paper_autotrade: when a paper trade exists,
this goes to the market, fetches the real price, and applies the SL / trailing
logic. Best-effort: a symbol whose quote can't be fetched is left untouched.

  manage.py poll_market [--user USERNAME]
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from traderacker import market
from traderacker.models import PaperTrade


class Command(BaseCommand):
    help = 'Fetch live prices and apply SL/trailing to open paper trades.'

    def add_arguments(self, parser):
        parser.add_argument('--user', default=None)

    def handle(self, *args, **opts):
        qs = PaperTrade.objects.open().select_related('user')
        if opts['user']:
            qs = qs.filter(user__username=opts['user'])

        priced = closed = skipped = 0
        for pt in qs:
            price, _src = market.get_price(pt.symbol, pt.asset_class)
            if price is None:
                skipped += 1
                continue
            priced += 1
            if pt.mark(price):
                closed += 1
        self.stdout.write(self.style.SUCCESS(
            f'Paper trades marked: {priced} priced · {closed} closed · {skipped} no-quote'))
