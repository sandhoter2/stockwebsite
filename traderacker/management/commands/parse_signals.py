"""Parse stored Telegram messages into Trade rows (signals + profit bookings).

Idempotent: trades are upserted by (channel, trade, entry). A CLOSED trade is
never reopened by a later re-post. Running profit is tracked via peak_profit;
an explicit exit (SAFE BOOK / TARGET HIT / …) or a trailing drawdown ≥30%
below the peak closes the trade at the best booked profit.

  manage.py parse_signals [--channel ID]
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from traderacker.models import TelegramMessage, Trade
from traderacker.signals import (parse_message, parse_profit, parse_exit,
                                 parse_exit_price)

TRAILING = 0.70   # close if running profit falls below 70% of peak (30% trail)
BUY_DIRECTIONS = {'BUY', 'CALL (UP)', 'LONG'}


class Command(BaseCommand):
    help = 'Parse TelegramMessage texts into Trade rows (signals + profit bookings).'

    def add_arguments(self, parser):
        parser.add_argument('--channel', type=int, default=None)
        parser.add_argument('--reclassify', action='store_true',
                            help='Backfill asset_class for ALL trades from the trade string')

    def handle(self, *args, **opts):
        if opts['reclassify']:
            from traderacker.signals import classify
            n = 0
            for t in Trade.objects.exclude(trade='').iterator():
                ac = classify(t.trade, t.direction, '')
                if ac != t.asset_class:
                    t.asset_class = ac
                    t.save(update_fields=['asset_class'])
                    n += 1
            self.stdout.write(self.style.SUCCESS(f'Reclassified {n} trades'))
            if opts.get('channel') is None and not Trade.objects.exists():
                return
        msgs = TelegramMessage.objects.select_related('channel').order_by('ts')
        if opts['channel']:
            msgs = msgs.filter(channel_id=opts['channel'])

        created = updated = closed = closed_at_price = 0

        def book(trade, profit, exiting):
            nonlocal closed
            if trade is None or profit is None:
                return
            peak = max(trade.peak_profit or 0, profit)
            trade.peak_profit = peak
            trail_hit = peak > 0 and profit < peak * TRAILING
            if (exiting or trail_hit) and trade.status != 'Closed':
                realized = max(trade.realized or 0, peak)
                # Another row may already occupy this (channel, date, trade, entry,
                # Closed) slot, e.g. two Open rows for the same re-posted signal both
                # getting closed. Merge into the existing closed twin instead of
                # violating uniq_trade_row, and drop this duplicate.
                dup = Trade.objects.filter(channel=trade.channel, date=trade.date,
                                           trade=trade.trade, entry=trade.entry,
                                           status='Closed').exclude(pk=trade.pk).first()
                if dup:
                    if dup.realized is None or realized > dup.realized:
                        dup.realized = realized
                        dup.save(update_fields=['realized'])
                    trade.delete()
                    closed += 1
                    return
                trade.status = 'Closed'
                trade.realized = realized
                closed += 1
                trade.save(update_fields=['peak_profit', 'status', 'realized'])
            else:
                trade.save(update_fields=['peak_profit'])

        def close_at_price(channel, symbol, price):
            """Close an Open trade by exit PRICE (not a rupee profit figure),
            e.g. 'EXIT RTNINDIA @ 63.3'. realized is the per-unit price delta,
            matching the sign convention entry/realized already use elsewhere
            (claimed_pct = realized / entry)."""
            nonlocal closed_at_price
            trade = Trade.objects.filter(channel=channel, status='Open',
                                         trade__iexact=symbol).first()
            if trade is None or trade.entry is None:
                return
            is_buy = (trade.direction or '').upper() in BUY_DIRECTIONS
            realized = round((price - trade.entry) if is_buy else (trade.entry - price), 2)
            # Another row may already occupy this (channel, date, trade, entry, Closed)
            # slot, e.g. two Open rows for the same re-posted signal both getting closed.
            # Flipping this one to Closed would collide with uniq_trade_row — merge into
            # the existing closed twin instead of crashing, and drop this duplicate.
            dup = Trade.objects.filter(channel=channel, date=trade.date, trade=trade.trade,
                                       entry=trade.entry, status='Closed').exclude(pk=trade.pk).first()
            if dup:
                if dup.realized is None or realized > dup.realized:
                    dup.ltp_exit = price
                    dup.realized = realized
                    dup.save(update_fields=['ltp_exit', 'realized'])
                trade.delete()
                closed_at_price += 1
                return
            trade.status = 'Closed'
            trade.ltp_exit = price
            trade.realized = realized
            closed_at_price += 1
            trade.save(update_fields=['status', 'ltp_exit', 'realized'])

        with transaction.atomic():
            for msg in msgs:
                signals = parse_message(msg.text, style=msg.channel.style)
                profit = parse_profit(msg.text)
                exiting = parse_exit(msg.text)
                exit_price = parse_exit_price(msg.text)
                if exit_price is not None:
                    close_at_price(msg.channel, exit_price[0], exit_price[1])
                if not signals and profit is None:
                    continue

                touched = []
                for sig in signals:
                    entry = sig['entry']
                    existing = Trade.objects.filter(
                        channel=msg.channel, trade=sig['trade'], entry=entry).first()
                    if existing:
                        # never reopen a closed trade; only fill blanks
                        upd = {}
                        if existing.asset_class in (None, '', 'other') and sig['asset_class'] != 'other':
                            upd['asset_class'] = sig['asset_class']
                        if existing.target is None and sig['target'] is not None:
                            upd['target'] = sig['target']
                        if existing.stop_loss is None and sig['stop_loss'] is not None:
                            upd['stop_loss'] = sig['stop_loss']
                        if existing.posted_at is None and msg.ts:
                            upd['posted_at'] = msg.ts
                            upd['source_mid'] = msg.mid
                        if existing.status == 'Open' and sig['direction'] and not existing.direction:
                            upd['direction'] = sig['direction']
                        if upd:
                            for k, v in upd.items():
                                setattr(existing, k, v)
                            existing.save(update_fields=list(upd))
                            updated += 1
                        touched.append(existing)
                    else:
                        defaults = {
                            'asset_class': sig['asset_class'],
                            'direction': sig['direction'],
                            'target': sig['target'], 'stop_loss': sig['stop_loss'],
                            'status': 'Open',
                            'posted_at': msg.ts, 'source_mid': msg.mid,
                        }
                        if msg.ts:
                            defaults['date'] = msg.ts.date()
                        t = Trade.objects.create(
                            channel=msg.channel, trade=sig['trade'], entry=entry,
                            **defaults)
                        created += 1
                        touched.append(t)

                # profit booking: prefer a trade touched by this message,
                # else the newest OPEN trade whose symbol appears in the text
                target = next((t for t in touched if t.status == 'Open'), None)
                if target is None and profit is not None:
                    words = sorted(
                        {w.strip('.,:;()[]#™®️') for w in msg.text.upper().split()
                         if len(w) >= 3 and any(c.isalpha() for c in w)},
                        key=len, reverse=True)
                    cand = Trade.objects.filter(channel=msg.channel, status='Open')
                    for w in words:
                        target = cand.filter(trade__icontains=w).order_by('-date').first()
                        if target:
                            break
                book(target, profit, exiting)

        self.stdout.write(self.style.SUCCESS(
            f'Signals: {created} new · {updated} updated · {closed} closed (exit/trailing) '
            f'· {closed_at_price} closed (exit price)'))
