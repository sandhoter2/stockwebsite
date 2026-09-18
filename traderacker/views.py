import csv
from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import filters, permissions, routers, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView


class IsStaffOrReadOnly(permissions.BasePermission):
    """Anyone authenticated can read; only staff can write. TradeViewSet was
    a full ModelViewSet with no write restriction at all before this --
    any signed-in customer could PATCH/DELETE any trade."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and
                    (request.method in permissions.SAFE_METHODS or request.user.is_staff))

from .models import (Channel, Event, PaperTrade, QuantityRule, Quote,
                     TelegramMessage, Trade, UserPreference, Watchlist)
from .serializers import (ChannelSerializer, PaperTradeSerializer,
                          QuantityRuleSerializer, QuoteSerializer,
                          TelegramMessageSerializer, TradeSerializer,
                          UserPreferenceSerializer, WatchlistSerializer)


class ChannelViewSet(viewsets.ModelViewSet):
    queryset = Channel.objects.annotate(
        trades_count=Count('trades'),
        open_count=Count('trades', filter=Q(trades__status='Open')),
        realized_total=Sum('trades__realized'),
        unrealized_total=Sum('trades__unrealized',
                             filter=Q(trades__status='Open')),
        invested_total=Sum('trades__entry'),
        wins=Count('trades', filter=Q(trades__status='Closed',
                                      trades__realized__gt=0)),
        losses=Count('trades', filter=Q(trades__status='Closed',
                                        trades__realized__lt=0)),
        booked=Count('trades', filter=Q(trades__status='Closed',
                                        trades__realized__isnull=False)),
    )
    serializer_class = ChannelSerializer
    search_fields = ('name', 'peer')


class TradeViewSet(viewsets.ModelViewSet):
    queryset = Trade.objects.select_related('channel')
    serializer_class = TradeSerializer
    filterset_fields = None
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['date', 'posted_at', 'channel__name', 'trade', 'entry',
                       'realized', 'unrealized', 'status', 'asset_class']
    ordering = ['-date']
    permission_classes = [IsStaffOrReadOnly]

    def perform_update(self, serializer):
        # Any inline admin edit (via the Trades table's edit-in-place UI)
        # sticks from here on: mark_live/close_eod both refuse to touch a
        # manually_edited row, so the next automated pass can't quietly
        # overwrite a correction a human just made.
        serializer.save(manually_edited=True)

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get('channel'):
            qs = qs.filter(channel_id=p['channel'])
        if p.get('status'):
            qs = qs.filter(status=p['status'])
        if p.get('sector'):
            qs = qs.filter(asset_class=p['sector'])
        if p.get('sectors'):
            qs = qs.sectors(p['sectors'].split(','))
        if p.get('date_from') or p.get('date_to'):
            qs = qs.in_range(p.get('date_from'), p.get('date_to'))
        if p.get('q'):
            qs = qs.filter(Q(trade__icontains=p['q']) |
                           Q(note__icontains=p['q']) |
                           Q(channel__name__icontains=p['q']))
        return qs


class QuoteViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Quote.objects.select_related('channel')
    serializer_class = QuoteSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get('channel'):
            qs = qs.filter(channel_id=p['channel'])
        if p.get('symbol'):
            qs = qs.filter(symbol__iexact=p['symbol'])
        return qs


class QuantityRuleViewSet(viewsets.ModelViewSet):
    queryset = QuantityRule.objects.all()
    serializer_class = QuantityRuleSerializer


class TelegramMessageViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TelegramMessage.objects.select_related('channel')
    serializer_class = TelegramMessageSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get('channel'):
            qs = qs.filter(channel_id=p['channel'])
        if p.get('q'):
            qs = qs.filter(text__icontains=p['q'])
        return qs


class SummaryView(APIView):
    """GET /api/tracker/summary/[?sectors=stock,option&date_from=&date_to=]
    — headline numbers for the dashboard cards (sector/range aware)."""

    def get(self, request):
        qs = _scoped_trades(request)
        week_ago = timezone.now() - timedelta(days=7)
        data = {
            'channels': qs.values_list('channel', flat=True).distinct().count(),
            'trades': qs.count(),
            'open_trades': qs.filter(status='Open').count(),
            'closed_trades': qs.filter(status='Closed').count(),
            'realized_total': qs.filter(
                date__gte=week_ago.date()).aggregate(s=Sum('realized'))['s'],
            'unrealized_total': qs.aggregate(s=Sum('unrealized'))['s'],
            'messages': TelegramMessage.objects.count(),
            'last_import': TelegramMessage.objects.order_by('-ts').values_list(
                'ts', flat=True).first(),
        }
        return Response(data)


def _parse_range(request):
    """Parse & validate date_from/date_to (ISO YYYY-MM-DD). 400 on garbage."""
    from django.utils.dateparse import parse_date

    out = {}
    for key in ('date_from', 'date_to'):
        raw = request.query_params.get(key)
        if not raw:
            continue
        val = parse_date(raw)
        if val is None:
            raise ValidationError({key: 'Expected ISO date YYYY-MM-DD.'})
        out[key] = val
    if out.get('date_from') and out.get('date_to') and \
            out['date_from'] > out['date_to']:
        raise ValidationError({'date_from': 'Must be on or before date_to.'})
    return out


def _sectors(request):
    """Parse ?sectors=stock,option,crypto,… → list of valid asset classes."""
    raw = request.query_params.get('sectors')
    if not raw:
        return None
    valid = {c[0] for c in Trade.ASSET_CHOICES}
    vals = [v.strip().lower() for v in raw.split(',') if v.strip()]
    bad = [v for v in vals if v not in valid]
    if bad:
        raise ValidationError({'sectors': 'Unknown: ' + ', '.join(bad)})
    return vals or None


def _scoped_trades(request):
    qs = Trade.objects.all()
    ch_id = request.query_params.get('channel')
    if ch_id:
        if not str(ch_id).isdigit():
            raise ValidationError({'channel': 'Must be an integer id.'})
        qs = qs.filter(channel_id=int(ch_id))
    qs = qs.sectors(_sectors(request))
    return qs.in_range(**_parse_range(request))


class ChannelStatsView(APIView):
    """GET /api/tracker/stats/[?channel=&date_from=&date_to=]

    Quick-glance track record: invested, returns, success rate, best/worst,
    monthly history and a cumulative realized equity curve.
    """

    def get(self, request):
        return Response(_scoped_trades(request).stats())


class BreakdownView(APIView):
    """GET /api/tracker/stats/breakdown/[?date_from=&date_to=]

    Per-channel aggregate rows for the leaderboard, date-range aware.
    """

    def get(self, request):
        return Response({'results': _scoped_trades(request).breakdown()})


class EventsView(APIView):
    """GET /api/tracker/events/?since=<id>[&limit=50]

    Cheap polling read for the frontend's live heartbeat to turn into an
    actual notification: "what happened since the last id I saw" instead
    of a full resync. Most-recent first; pass the highest `id` you've
    already seen as `since` to get only what's new.
    """

    def get(self, request):
        since = request.query_params.get('since')
        limit = min(int(request.query_params.get('limit', 50) or 50), 200)
        qs = Event.objects.select_related('channel', 'trade')
        if since:
            qs = qs.filter(id__gt=since)
        rows = qs[:limit]
        return Response({'results': [
            {'id': e.id, 'kind': e.kind, 'message': e.message,
             'channel': e.channel_id, 'trade': e.trade_id,
             'created_at': e.created_at}
            for e in rows]})


class PicksView(APIView):
    """GET /api/tracker/picks/[?sectors=&date_from=&date_to=&channel=]

    Cross-channel consensus: for each symbol, how many recommendations lean
    BUY vs SELL (favorite picks panel).
    """

    def get(self, request):
        limit = min(int(request.query_params.get('limit', 25) or 25), 100)
        return Response({'results': _scoped_trades(request).picks(limit=limit)})


class TodaysCallsView(APIView):
    """GET /api/tracker/calls/[?hours=24&channel=&sectors=]

    Live feed: recent trade calls across all channels, posted within the
    last `hours` (default 24, max 30 days), sorted by the posting channel's
    trust tier / confidence score so the most credible calls surface first.
    """

    def get(self, request):
        raw_hours = request.query_params.get('hours', 24)
        try:
            hours = int(raw_hours)
        except (TypeError, ValueError):
            raise ValidationError({'hours': 'Must be an integer.'})
        hours = min(max(hours, 1), 24 * 30)

        qs = Trade.objects.all()
        ch_id = request.query_params.get('channel')
        if ch_id:
            if not str(ch_id).isdigit():
                raise ValidationError({'channel': 'Must be an integer id.'})
            qs = qs.filter(channel_id=int(ch_id))
        qs = qs.sectors(_sectors(request))
        return Response({'results': qs.todays_calls(hours=hours), 'hours': hours})


class TradesExportView(APIView):
    """GET /api/tracker/trades/export/[?channel=&sectors=&status=&date_from=&date_to=]

    CSV download of matching trades — the full ledger, or a single channel's
    track record when `channel` is given.
    """

    def get(self, request):
        qs = _scoped_trades(request).select_related('channel')
        status = request.query_params.get('status')
        if status:
            qs = qs.filter(status=status)

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="trades.csv"'
        writer = csv.writer(response)
        writer.writerow(['channel', 'asset_class', 'date', 'trade', 'direction',
                         'entry', 'target', 'stop_loss', 'ltp_exit', 'unrealized',
                         'realized', 'status', 'posted_at'])
        for t in qs.order_by('channel__name', 'date'):
            writer.writerow([
                t.channel.short or t.channel.name, t.asset_class, t.date, t.trade,
                t.direction, t.entry, t.target, t.stop_loss, t.ltp_exit,
                t.unrealized, t.realized, t.status,
                t.posted_at.isoformat() if t.posted_at else '',
            ])
        return response


class WatchlistViewSet(viewsets.ModelViewSet):
    """Per-user followed channels: list/add/remove (own only), so the
    frontend can build a 'my channels' filter."""
    serializer_class = WatchlistSerializer
    http_method_names = ['get', 'post', 'delete']

    def get_queryset(self):
        return Watchlist.objects.filter(
            user=self.request.user).select_related('channel')

    def perform_create(self, serializer):
        # idempotent follow: re-posting an already-followed channel just
        # returns the existing row instead of tripping the uniqueness constraint
        channel = serializer.validated_data['channel']
        obj, _ = Watchlist.objects.get_or_create(
            user=self.request.user, channel=channel)
        serializer.instance = obj


class PaperViewSet(viewsets.ModelViewSet):
    """Per-user paper trades: list, manual create, delete (own only)."""
    serializer_class = PaperTradeSerializer
    http_method_names = ['get', 'post', 'delete']
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['opened_at', 'closed_at', 'symbol', 'status', 'realized_inr', 'realized_pct']
    ordering = ['-opened_at']

    def get_queryset(self):
        qs = PaperTrade.objects.filter(user=self.request.user).select_related(
            'user', 'source_trade__channel')
        st = self.request.query_params.get('status')
        if st:
            qs = qs.filter(status=st)
        q = self.request.query_params.get('q')
        if q:
            qs = qs.filter(symbol__icontains=q)
        return qs

    def perform_create(self, serializer):
        pref = UserPreference.for_user(self.request.user)
        entry = serializer.validated_data['entry_price']
        serializer.save(
            user=self.request.user, is_manual=True, price_source='manual',
            notional_inr=serializer.validated_data.get('notional_inr')
            or pref.capital_per_trade,
            current_price=entry, highest_price=entry, lowest_price=entry,
            stop_loss_pct=serializer.validated_data.get('stop_loss_pct')
            or pref.stop_loss_pct,
            trailing_pct=serializer.validated_data.get('trailing_pct')
            or pref.trailing_pct)

    @action(detail=False, methods=['get'], url_path='accuracy')
    def accuracy(self, request):
        return Response({'results': PaperTrade.objects.channel_accuracy(
            user=request.user)})


class PrefsView(APIView):
    """GET/PUT /api/tracker/prefs/ — the signed-in user's paper preferences."""

    def get(self, request):
        pref = UserPreference.for_user(request.user)
        return Response(UserPreferenceSerializer(pref).data)

    def put(self, request):
        pref = UserPreference.for_user(request.user)
        ser = UserPreferenceSerializer(pref, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)


class PaperAutotradeNowView(APIView):
    """POST /api/tracker/paper/autotrade/

    Runs paper_autotrade for just the signed-in user, synchronously, scoped
    to their own auto_consumers -- so saving a channel selection in the
    Paper Trading picker has an immediate, visible effect instead of only
    taking effect whenever the live-sync cron next ticks (up to 2 min).
    Cheap: one user, filtered to their configured channels only.
    """

    def post(self, request):
        from io import StringIO

        from django.core.management import call_command
        out = StringIO()
        call_command('paper_autotrade', user=request.user.username, stdout=out)
        return Response({'detail': out.getvalue().strip()})


class TrackerRouter(routers.DefaultRouter):
    """DRF router with the tracker registrations."""

    def __init__(self):
        super().__init__()
        self.register('channels', ChannelViewSet)
        self.register('trades', TradeViewSet)
        self.register('quotes', QuoteViewSet)
        self.register('quantities', QuantityRuleViewSet)
        self.register('messages', TelegramMessageViewSet)
        self.register('paper', PaperViewSet, basename='paper')
        self.register('watchlist', WatchlistViewSet, basename='watchlist')
