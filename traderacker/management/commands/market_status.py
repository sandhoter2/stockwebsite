"""Cheap exit-code check for shell scripts: is NSE open right now?

  manage.py market_status   # prints open/closed, exit 0 if open else 1

Used by scripts/live_market_sync.sh to no-op instantly outside trading
hours instead of doing real work (or scheduling cron around IST, which
drifts against the host's own DST).
"""
from django.core.management.base import BaseCommand

from traderacker.market_hours import is_market_open


class Command(BaseCommand):
    help = 'Exit 0 and print "open" if NSE is in session right now, else exit 1 and print "closed".'

    def handle(self, *args, **opts):
        open_ = is_market_open()
        self.stdout.write('open' if open_ else 'closed')
        if not open_:
            raise SystemExit(1)
