"""LLM-assisted close interpretation for messages the regex parser
(signals.py/parse_signals) can't confidently read -- see traderacker/
llm_triage.py's module docstring for the safety design (never trusts a
price the LLM claims unless that exact number is literally present in the
source message text).

Candidate messages: for each channel with at least one Open trade, every
message posted AFTER that trade's entry that mentions the trade's root
symbol, produced NO signal via parse_message, and hasn't been triaged
before (tracked in ProcessedProfitEvent with kind='llm_triage', reusing the
same durable per-message tracking parse_signals itself relies on so a
message is never re-sent to the LLM on a later run).

No-op (not an error) if USER_OMNIROUTE_API_KEY isn't configured --
llm_triage.is_configured() gates the whole run so this is safe to include
in an automated pipeline before the key exists.

  manage.py llm_triage [--channel ID] [--limit N] [--dry-run]
"""
from django.core.management.base import BaseCommand

from traderacker import llm_triage
from traderacker.models import Channel, ProcessedProfitEvent, TelegramMessage, Trade
from traderacker.signals import parse_message


class Command(BaseCommand):
    help = "LLM-interpret ambiguous messages (bare-number closes etc) the regex parser can't read."

    def add_arguments(self, parser):
        parser.add_argument('--channel', type=int, default=None)
        parser.add_argument('--limit', type=int, default=200,
                            help='Cap candidate messages examined per run.')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        if not llm_triage.is_configured():
            self.stdout.write(self.style.WARNING(
                'USER_OMNIROUTE_API_KEY not set -- nothing to do (this is a no-op, not an error).'))
            return

        channels = Channel.objects.filter(trades__status='Open').distinct()
        if opts['channel']:
            channels = channels.filter(id=opts['channel'])

        already = set(ProcessedProfitEvent.objects.filter(kind='llm_triage')
                      .values_list('channel_id', 'mid'))
        examined = closed = 0
        for channel in channels:
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
                if examined >= opts['limit']:
                    break
                if (channel.id, msg.mid) in already:
                    continue
                text_upper = (msg.text or '').upper()
                if not any(r in text_upper for r in roots):
                    continue
                if parse_message(msg.text, style=channel.style):
                    continue  # regex already handled this one
                examined += 1
                new_event = ProcessedProfitEvent(channel=channel, mid=msg.mid, kind='llm_triage')
                if opts['dry_run']:
                    continue
                new_event.save()
                already.add((channel.id, msg.mid))

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

        verb = 'would examine' if opts['dry_run'] else 'examined'
        self.stdout.write(self.style.SUCCESS(
            f'LLM triage: {verb} {examined} candidate message(s), closed {closed} trade(s).'))
