"""Parse stored Telegram messages into Trade rows (signals + profit bookings).

Idempotent: trades are upserted by (channel, trade, entry). A CLOSED trade is
never reopened by a later re-post. Running profit is tracked via peak_profit;
an explicit exit (SAFE BOOK / TARGET HIT / …) or a trailing drawdown ≥30%
below the peak closes the trade at the best booked profit.

A stated profit figure with no directly-touched trade is attributed to the
Open trade whose FULL symbol string (root + strike/right, e.g. "NIFTY 23650
PE") appears verbatim in the message -- never a loose single-word substring
match ("NIFTY" alone), which would silently misattribute the same figure to
whichever neighbouring leg of that index happens to still be Open once the
real one is Closed.

Every profit/exit-price message is recorded in ProcessedProfitEvent once
considered, whether or not it found a target -- this replay processes the
full message history in chronological order every run, creating Trade rows
lazily as their entry message is reached, so a message whose OWN timestamp
precedes its target's entry message legitimately finds nothing on a run that
starts from an empty Trade table. Without a durable "already considered"
record, a second run (against a Trade table that wasn't cleared -- the
normal way this command gets re-run) would find some *other* trade that only
exists because it was created later in THIS SAME earlier run, and wrongly
attach the stale message to it. See ProcessedProfitEvent's docstring and
docs/AGENT_HANDOFF.md §7.

  manage.py parse_signals [--channel ID]
"""
import datetime as dt
import re

from django.core.management.base import BaseCommand
from django.db import transaction

from traderacker.models import ProcessedProfitEvent, TelegramMessage, Trade
from traderacker.signals import (parse_message, parse_profit, parse_exit,
                                 parse_exit_price)

TRAILING = 0.70   # close if running profit falls below 70% of peak (30% trail)
BUY_DIRECTIONS = Trade.BUY_DIRECTIONS


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
        # 'mid' as a tiebreaker makes the order fully deterministic: 2,510+
        # groups of messages share an identical 'ts' (up to 23 messages at
        # the same second), and ORDER BY on 'ts' alone has no guaranteed
        # stable order for ties. mid is monotonically assigned by Telegram,
        # so it's a safe, meaningful secondary sort, not an arbitrary one.
        msgs = TelegramMessage.objects.select_related('channel').order_by('ts', 'mid')
        if opts['channel']:
            msgs = msgs.filter(channel_id=opts['channel'])

        # peak_profit is DERIVED state -- reconstructed by replaying every
        # message for this trade's channel(s) in chronological order below --
        # not something to carry forward from a prior invocation. Left as-is,
        # a second run would start from last run's final (highest) peak, so
        # an early/lower-profit message this time immediately looks like a
        # trailing-stop breach against a peak it hasn't actually reached yet
        # in this pass, closing the trade prematurely. Reset before replaying
        # so every run reconstructs the same trajectory from the same inputs.
        reset_scope = Trade.objects.all()
        event_scope = ProcessedProfitEvent.objects.all()
        if opts['channel']:
            reset_scope = reset_scope.filter(channel_id=opts['channel'])
            event_scope = event_scope.filter(channel_id=opts['channel'])
        reset_scope.update(peak_profit=None)

        # preload which (channel, mid, kind) events have already been
        # considered in a prior run, and collect new ones to write in bulk
        # at the end rather than one row per message.
        processed = set(event_scope.values_list('channel_id', 'mid', 'kind'))
        new_events = []

        def mark_processed(channel_id, mid, kind):
            key = (channel_id, mid, kind)
            if key not in processed:
                processed.add(key)
                new_events.append(ProcessedProfitEvent(channel_id=channel_id, mid=mid, kind=kind))

        created = updated = closed = closed_at_price = 0

        def book(trade, profit, exiting):
            nonlocal closed
            if trade is None or profit is None:
                return
            peak = max(trade.peak_profit or 0, profit)
            trade.peak_profit = peak
            trail_hit = peak > 0 and profit < peak * TRAILING
            if (exiting or trail_hit) and trade.status != 'Closed':
                is_opt = trade.asset_class == 'option' or bool(trade.option_strike())
                if trade.entry is not None and trade.ltp_exit is not None:
                    if is_opt:
                        realized = round(trade.ltp_exit - trade.entry, 2)
                    else:
                        is_buy = (trade.direction or '').upper() in BUY_DIRECTIONS
                        realized = round((trade.ltp_exit - trade.entry) if is_buy else (trade.entry - trade.ltp_exit), 2)
                else:
                    # Peak profit from message is total rupee figure. If instrument has a lot multiplier > 1,
                    # convert to per-unit delta so Trade.realized_total equals the original booked profit.
                    lot = trade.lot_size
                    if lot > 1 and peak > lot:
                        realized = round(peak / lot, 2)
                    else:
                        realized = round(peak, 2)

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
            is_opt = trade.asset_class == 'option' or bool(trade.option_strike())
            if is_opt:
                realized = round(price - trade.entry, 2)
            else:
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
                    if (msg.channel_id, msg.mid, 'exit_price') not in processed:
                        close_at_price(msg.channel, exit_price[0], exit_price[1])
                        mark_processed(msg.channel_id, msg.mid, 'exit_price')
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
                # else the OPEN trade whose FULL symbol string is stated in
                # the text (never a loose single-word substring like "NIFTY"
                # alone, which would match every leg of that index and
                # misattribute the figure once the real leg is Closed).
                # Gated on (channel, mid) regardless of which path finds the
                # target: book() mutates peak_profit/status based on this
                # message's profit figure, so re-running it a second time
                # against a trade whose peak_profit was just reset to None
                # would replay the same trailing-stop trajectory from
                # scratch and can land on a different outcome mid-replay.
                if profit is not None and (msg.channel_id, msg.mid, 'profit') not in processed:
                    target = next((t for t in touched if t.status == 'Open'), None)
                    if target is None:
                        msg_norm = re.sub(r'\s+', ' ', msg.text.upper())
                        cand = Trade.objects.filter(channel=msg.channel, status='Open',
                                                    trade__isnull=False).exclude(trade='')
                        if msg.ts:
                            cand = cand.filter(date__lte=msg.ts.date())
                        matches = list(cand.order_by('id'))
                        matches = [c for c in matches
                                  if re.sub(r'\s+', ' ', c.trade.upper()) in msg_norm]
                        # prefer the most specific (longest) symbol string, then
                        # the most recently opened, then insertion order (id) as
                        # a final deterministic tiebreaker -- .sort() is stable,
                        # and the queryset above is now explicitly ordered, so
                        # ties resolve the same way on every run.
                        matches.sort(key=lambda c: (len(c.trade), c.date or dt.date.min),
                                    reverse=True)
                        target = matches[0] if matches else None
                    mark_processed(msg.channel_id, msg.mid, 'profit')
                    book(target, profit, exiting)

            ProcessedProfitEvent.objects.bulk_create(new_events, ignore_conflicts=True)

        self.stdout.write(self.style.SUCCESS(
            f'Signals: {created} new · {updated} updated · {closed} closed (exit/trailing) '
            f'· {closed_at_price} closed (exit price)'))
