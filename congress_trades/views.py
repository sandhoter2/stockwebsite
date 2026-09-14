from rest_framework import routers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import CongressTrade
from .serializers import CongressTradeSerializer


class CongressTradeViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/congress/trades/?politician=&ticker=&party=&chamber=&days=

    Read-only feed of disclosed Congress stock trades, most recent
    disclosure first. Defaults to the last 45 days since STOCK Act filings
    lag the actual trade date by weeks. Each row is pre-formatted with a
    terse `summary_line` so the frontend doesn't need to assemble one.
    """
    queryset = CongressTrade.objects.all()
    serializer_class = CongressTradeSerializer

    def _days(self):
        raw = self.request.query_params.get('days', 45)
        try:
            days = int(raw)
        except (TypeError, ValueError):
            raise ValidationError({'days': 'Must be an integer.'})
        return min(max(days, 1), 365)

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


class CongressRouter(routers.DefaultRouter):
    def __init__(self):
        super().__init__()
        self.register('trades', CongressTradeViewSet, basename='congress-trades')
