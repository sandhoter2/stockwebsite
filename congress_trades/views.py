from django.db import models
from rest_framework import filters, routers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import CongressTrade
from .serializers import CongressTradeSerializer, PoliticianBreakdownSerializer


class CongressTradeViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/congress/trades/?politician=&ticker=&party=&chamber=&days=

    Read-only feed of disclosed Congress stock trades, most recent
    disclosure first. Defaults to the last 45 days since STOCK Act filings
    lag the actual trade date by weeks. Each row is pre-formatted with a
    terse `summary_line` so the frontend doesn't need to assemble one.
    """
    queryset = CongressTrade.objects.all()
    serializer_class = CongressTradeSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['transaction_date', 'disclosure_date', 'politician_name',
                       'ticker', 'amount_max', 'chamber', 'party']
    ordering = ['-disclosure_date', '-transaction_date']

    def _days(self):
        raw = self.request.query_params.get('days', 45)
        try:
            days = int(raw)
        except (TypeError, ValueError):
            raise ValidationError({'days': 'Must be an integer.'})
        return min(max(days, 1), 3650)

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get('politician'):
            qs = qs.filter(politician_name__icontains=p['politician'])
        if p.get('ticker'):
            qs = qs.filter(ticker__iexact=p['ticker'])
        if p.get('party'):
            qs = qs.filter(party=p['party'].upper())
        if p.get('chamber'):
            qs = qs.filter(chamber__iexact=p['chamber'])
        if p.get('transaction_type'):
            qs = qs.filter(transaction_type=p['transaction_type'])
        if p.get('q'):
            qs = qs.filter(models.Q(politician_name__icontains=p['q']) |
                           models.Q(ticker__icontains=p['q']) |
                           models.Q(asset_description__icontains=p['q']))
        return qs.recent(days=self._days())

    @action(detail=False, methods=['get'], url_path='notable')
    def notable(self, request):
        """GET /api/congress/trades/notable/[?days=60&limit=20]

        Curated list of the largest recent trades — the action-oriented
        default the frontend should show instead of the full feed.
        """
        days = min(max(int(request.query_params.get('days', 60) or 60), 1), 365)
        limit = min(max(int(request.query_params.get('limit', 20) or 20), 1), 100)
        rows = CongressTrade.objects.notable(days=days, limit=limit)
        return Response({'results': CongressTradeSerializer(rows, many=True).data,
                         'days': days})

    @action(detail=False, methods=['get'], url_path='politicians')
    def politicians(self, request):
        """GET /api/congress/trades/politicians/[?days=&party=&chamber=]

        Per-politician leaderboard — trade counts, win rate on closed
        round-trips, realized/unrealized profit totals and a trust tier
        (reusing traderacker's Wilson-score tiering), mirroring
        traderacker's /stats/breakdown/ channel leaderboard.
        """
        qs = CongressTrade.objects.all()
        p = self.request.query_params
        if p.get('party'):
            qs = qs.filter(party=p['party'].upper())
        if p.get('chamber'):
            qs = qs.filter(chamber__iexact=p['chamber'])
        if p.get('days'):
            try:
                days = min(max(int(p['days']), 1), 3650)
            except (TypeError, ValueError):
                raise ValidationError({'days': 'Must be an integer.'})
            qs = qs.recent(days=days)
        rows = qs.politician_breakdown()
        return Response({'results': PoliticianBreakdownSerializer(rows, many=True).data})

    @action(detail=False, methods=['get'], url_path='politician-profile')
    def politician_profile(self, request):
        """GET /api/congress/trades/politician-profile/?politician=<name>

        One politician's full profile: their leaderboard row (trust tier,
        win rate, realized/unrealized totals) plus their complete trade
        history — mirrors the channel profile pattern (breakdown row +
        that channel's trades), scoped to a single politician.
        """
        name = request.query_params.get('politician')
        if not name:
            raise ValidationError({'politician': 'Required.'})
        qs = CongressTrade.objects.filter(politician_name__iexact=name)
        if not qs.exists():
            return Response({'detail': 'No trades found for this politician.'}, status=404)
        profile_rows = CongressTrade.objects.filter(
            politician_name__iexact=name).politician_breakdown()
        profile = profile_rows[0] if profile_rows else None
        trades = qs.order_by('-transaction_date', '-disclosure_date')
        return Response({
            'profile': PoliticianBreakdownSerializer(profile).data if profile else None,
            'trades': CongressTradeSerializer(trades, many=True).data,
        })


class CongressRouter(routers.DefaultRouter):
    def __init__(self):
        super().__init__()
        self.register('trades', CongressTradeViewSet, basename='congress-trades')
