"""Open paper trades from consumer signals at REAL market price.

Runs after parse_signals. For each user with auto_paper on, for each of their
auto_consumers (defaulted to the top-10 leaderboard), open a PaperTrade for
every parsed signal not already paper-traded — priced via the market service
(Yahoo→Dhan), falling back to the consumer's posted price (flagged) if no live
quote is available. Requirement: entry uses market value, NOT the consumer's
posted price, when a live quote exists.
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum

from traderacker import market
from traderacker.models import Channel, PaperTrade, Trade, UserPreference

BUY_DIRECTIONS = {'BUY', 'CALL (UP)', 'LONG'}


def side_for(direction):
    return 'BUY' if (direction or '').upper() in BUY_DIRECTIONS else 'SELL'


class Command(BaseCommand):
    help = 'Auto-open paper trades from consumer signals at market price.'

    def add_arguments(self, parser):
        parser.add_argument('--user', default=None, help='Only this username')
        parser.add_argument('--days', type=int, default=30,
                            help='Only signals posted within N days (0 = all)')

    def _seed_auto_consumers(self, pref):
        if pref.auto_consumers.exists():
            return
        top = (Channel.objects.annotate(r=Sum('trades__realized'))
               .order_by('-r')[:10])
        pref.auto_consumers.set(top)

    def handle(self, *args, **opts):
        from django.utils import timezone
        import datetime as dt

        users = User.objects.all()
        if opts['user']:
            users = users.filter(username=opts['user'])
        cutoff = (timezone.now() - dt.timedelta(days=opts['days'])) if opts['days'] else None

        opened = 0
        with transaction.atomic():
            for user in users:
                pref = UserPreference.for_user(user)
                if not pref.auto_paper:
                    continue
                self._seed_auto_consumers(pref)
                channels = list(pref.auto_consumers.all())
                existing = set(PaperTrade.objects.filter(user=user)
                               .values_list('source_trade_id', flat=True))
                qs = Trade.objects.filter(channel__in=channels,
                                          source_mid__isnull=False,
                                          status='Open')
                if cutoff:
                    qs = qs.filter(posted_at__gte=cutoff)
                for t in qs.exclude(id__in=existing).select_related('channel'):
                    price, source = market.get_price(t.root_symbol, t.asset_class)
                    if price is None:
                        price, source = t.entry, 'posted'   # fallback, flagged
                    if not price:
                        continue
                    PaperTrade.open_for_user(
                        user, t.root_symbol, t.asset_class, side_for(t.direction),
                        price, source=source, source_trade=t,
                        consumer_claimed_pct=t.claimed_pct)
                    opened += 1
        self.stdout.write(self.style.SUCCESS(f'Paper trades opened: {opened}'))
