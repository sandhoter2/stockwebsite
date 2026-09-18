"""Cheap exit-code check for shell scripts: are we in the once-daily
pre-market catch-up window (a few minutes around 7:00 IST) right now?

  manage.py premarket_status   # exit 0 if yes, 1 if no

Used by scripts/live_market_sync.sh to decide whether this tick should do
the bigger overnight Telegram catch-up (--limit 500) instead of the usual
small intraday one (--limit 30).
"""
from django.core.management.base import BaseCommand

from traderacker.market_hours import is_premarket_window


class Command(BaseCommand):
    help = 'Exit 0 if it is the ~7am IST pre-market catch-up window right now, else exit 1.'

    def handle(self, *args, **opts):
        in_window = is_premarket_window()
        self.stdout.write('yes' if in_window else 'no')
        if not in_window:
            raise SystemExit(1)
