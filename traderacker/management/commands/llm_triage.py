"""LLM-assisted interpretation for messages the regex parser
(signals.py/parse_signals) can't confidently read -- see traderacker/
llm_triage.py's module docstring for the safety design (never trusts a
price the LLM claims -- open OR close -- unless that exact number is
literally present in the source message text).

Two passes, both durably tracked in ProcessedProfitEvent (kind='llm_triage',
reusing the same per-message tracking parse_signals itself relies on) so a
message is never re-sent to the LLM twice:

1. CLOSE candidates: for each channel with at least one Open trade, every
   message that mentions one of those trades' root symbols, produced NO
   signal via parse_message, and is dated on/after that trade's own date.

2. OPEN candidates: TODAY's messages only (an LLM-driven scan of years of
   historical backlog would be needless cost -- the regex parser already
   covers that history), across every active channel, that pass the cheap
   looks_like_possible_open() pre-filter and produced no signal via
   parse_message.

No-op (not an error) if USER_OMNIROUTE_API_KEY isn't configured --
llm_triage.is_configured() gates the whole run so this is safe to include
in an automated pipeline before the key exists.

  manage.py llm_triage [--channel ID] [--limit N] [--dry-run]
"""
from django.core.management.base import BaseCommand
from django.db import IntegrityError

from traderacker import llm_triage
from traderacker.market_hours import ist_today
from traderacker.models import Channel, ProcessedProfitEvent, TelegramMessage, Trade
from traderacker.signals import parse_message


class Command(BaseCommand):
    help = "LLM-interpret ambiguous messages (bare-number closes, unrecognized opens) the regex parser can't read."

    def add_arguments(self, parser):
        parser.add_argument('--channel', type=int, default=None)
        parser.add_argument('--limit', type=int, default=200,
                            help='Cap candidate messages examined per run (shared across both passes).')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        if not llm_triage.is_configured():
            self.stdout.write(self.style.WARNING(
                'USER_OMNIROUTE_API_KEY not set -- nothing to do (this is a no-op, not an error).'))
            return

        dry_run = opts['dry_run']
        limit = opts['limit']
        already = set(ProcessedProfitEvent.objects.filter(kind='llm_triage')
                      .values_list('channel_id', 'mid'))
        examined = closed = opened = 0

        def mark_examined(channel, mid):
            nonlocal examined
            examined += 1
            if not dry_run:
                ProcessedProfitEvent.objects.create(channel=channel, mid=mid, kind='llm_triage')
            already.add((channel.id, mid))

        # --- Pass 1: closes -----------------------------------------
        close_channels = Channel.objects.filter(trades__status='Open').distinct()
        if opts['channel']:
            close_channels = close_channels.filter(id=opts['channel'])

        for channel in close_channels:
            if examined >= limit:
                break
            open_trades = list(Trade.objects.filter(channel=channel, status='Open')
                               .values('id', 'trade', 'entry', 'target', 'stop_loss', 'date'))
            if not open_trades:
                continue
            roots = {t['trade'].split()[0].upper() for t in open_trades if t['trade']}
            earliest_date = min((t['date'] for t in open_trades if t['date']), default=None)
            msgs = TelegramMessage.objects.filter(channel=channel)
            if earliest_date:
                msgs = msgs.filter(ts__date__gte=earliest_date)
            msgs = msgs.order_by('ts')

            for msg in msgs:
                if examined >= limit:
                    break
                if (channel.id, msg.mid) in already:
                    continue
                text_upper = (msg.text or '').upper()
                if not any(r in text_upper for r in roots):
                    continue
                if parse_message(msg.text, style=channel.style):
                    continue  # regex already handled this one
                mark_examined(channel, msg.mid)
                if dry_run:
                    continue

                result = llm_triage.interpret_close(msg.text, open_trades)
                if not result:
                    continue
                trade = next((t for t in open_trades if t['trade'] == result['trade']), None)
                if not trade:
                    continue
                row = Trade.objects.filter(id=trade['id'], status='Open',
                                           manually_edited=False).first()
                if not row:
                    continue
                row.status = 'Closed'
                row.ltp_exit = result['price']
                row.realized = round(result['price'] - row.entry, 2) if row.entry is not None else None
                row.note = (row.note + f" [llm-closed@{result['price']}: {result['reasoning']}]").strip()
                row.save(update_fields=['status', 'ltp_exit', 'realized', 'note'])
                open_trades = [t for t in open_trades if t['id'] != row.id]
                closed += 1

        # --- Pass 2: opens (today's messages only) --------------------
        open_channels = Channel.objects.filter(is_active=True)
        if opts['channel']:
            open_channels = open_channels.filter(id=opts['channel'])
        today = ist_today()

        for channel in open_channels:
            if examined >= limit:
                break
            msgs = TelegramMessage.objects.filter(
                channel=channel, ts__date=today).order_by('ts')
            for msg in msgs:
                if examined >= limit:
                    break
                if (channel.id, msg.mid) in already:
                    continue
                if not llm_triage.looks_like_possible_open(msg.text):
                    continue
                # Unlike the close pass, a non-empty parse_message() result
                # here isn't necessarily "already handled" -- RE_OPT can
                # match the instrument with entry=None (no real trigger
                # phrase found), which is a phantom the regex parser itself
                # already treats as unusable. Only a signal with a real
                # entry price counts as "regex already got this."
                if any(sig.get('entry') is not None
                      for sig in parse_message(msg.text, style=channel.style)):
                    continue
                mark_examined(channel, msg.mid)
                if dry_run:
                    continue

                result = llm_triage.interpret_open(msg.text)
                if not result:
                    continue
                exists = Trade.objects.filter(
                    channel=channel, trade=result['trade'], entry=result['entry'],
                    status='Open').exists()
                if exists:
                    continue
                try:
                    Trade.objects.create(
                        channel=channel, trade=result['trade'], direction=result['direction'],
                        asset_class=result['asset_class'], entry=result['entry'],
                        target=result['target'], stop_loss=result['stop_loss'],
                        status='Open', date=msg.ts.date() if msg.ts else today,
                        posted_at=msg.ts, source_mid=msg.mid,
                        note=f"[llm-opened: {result['reasoning']}]")
                except IntegrityError:
                    continue
                opened += 1

        verb = 'would examine' if dry_run else 'examined'
        self.stdout.write(self.style.SUCCESS(
            f'LLM triage: {verb} {examined} candidate message(s), '
            f'closed {closed} trade(s), opened {opened} trade(s).'))
