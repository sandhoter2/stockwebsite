"""Upgrade close_eod()'s same-day intrinsic-value *estimate* to the real
NSE closing premium, once NSE actually publishes it.

close_eod() force-squares-off day calls in the 15:27-15:30 IST window,
before NSE's official bhavcopy exists -- so it prices options against
intrinsic value (spot vs strike), which ignores time value and is flagged
as an estimate in the note. This command runs later (intended: a nightly
cron a good while after 18:00 IST, once NSE has published that day's F&O
UDiFF bhavcopy) and replaces the estimate with the real traded closing
premium wherever NSE has one.

  manage.py reconcile_eod_settlement [--date YYYY-MM-DD]

Only touches Trade rows still tagged '[eod-closed:estimated intrinsic
value ...]' -- a row already reconciled, or closed with a real quote, or
manually edited since, is left alone.
"""
import datetime as dt

from django.core.management.base import BaseCommand

from traderacker.market_hours import ist_today
from traderacker.models import Trade
from traderacker.nse_bhavcopy import official_option_close

ESTIMATE_MARKER = 'estimated intrinsic value'
# Underlyings settled on NSE F&O only -- BSE's SENSEX/BANKEX and MCX
# commodities/metals have no row in the NSE bhavcopy and must stay estimates.
NON_NSE_MARKERS = ('SENSEX', 'BANKEX', 'CRUDE', 'OIL', 'NATURALGAS', 'NATGAS',
                   'GOLD', 'SILVER', 'COPPER', 'ZINC', 'ALUMINUM', 'ALUMINIUM')


class Command(BaseCommand):
    help = "Replace close_eod()'s intrinsic-value option estimates with NSE's real closing premium."

    def add_arguments(self, parser):
        parser.add_argument('--date', default=None,
                            help='Trading date YYYY-MM-DD (default: today, IST). '
                                 "NSE's daily-reports API only serves the current/previous trading day.")

    def handle(self, *args, **opts):
        target_date = (dt.datetime.strptime(opts['date'], '%Y-%m-%d').date()
                       if opts['date'] else ist_today())

        qs = Trade.objects.filter(status='Closed', date=target_date,
                                  note__contains=ESTIMATE_MARKER, manually_edited=False)
        reconciled = no_data = skipped = 0
        for t in qs:
            if t.asset_class in ('commodity', 'metal') or any(
                    m in (t.trade or '').upper() for m in NON_NSE_MARKERS):
                skipped += 1
                continue
            parsed = t.option_strike()
            if not parsed:
                skipped += 1
                continue
            strike, opt_type = parsed
            price = official_option_close(t.root_symbol, strike, opt_type, target_date)
            if price is None:
                no_data += 1
                continue
            old_tag = f'[eod-closed:estimated intrinsic value @ {t.ltp_exit}]'
            t.ltp_exit = price
            t.realized = round(price - t.entry, 2) if t.entry is not None else None
            new_tag = f'[eod-closed:reconciled to NSE settlement price @ {price}]'
            t.note = (t.note.replace(old_tag, '') + ' ' + new_tag).strip()
            t.save(update_fields=['ltp_exit', 'realized', 'note'])
            reconciled += 1

        self.stdout.write(self.style.SUCCESS(
            f'Reconciled {reconciled} trade(s) against NSE {target_date} settlement · '
            f'{no_data} no NSE data · {skipped} skipped (non-NSE/unparseable)'))
