from rest_framework import routers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Holding, SuperInvestor
from .serializers import HoldingSerializer, SuperInvestorSerializer


def _iso_moves(results):
    """Mutate a list of moves()/investor_profile() row dicts in place,
    turning their date objects into ISO strings for JSON."""
    for r in results:
        r['filing_quarter'] = r['filing_quarter'].isoformat() if r['filing_quarter'] else None
        r['filed_date'] = r['filed_date'].isoformat() if r['filed_date'] else None
    return results


class SuperInvestorViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SuperInvestor.objects.all()
    serializer_class = SuperInvestorSerializer

    @action(detail=True, methods=['get'])
    def profile(self, request, pk=None):
        """GET /api/super-investors/investors/<id>/profile/

        Per-investor profile mirroring traderacker's Channel stats pattern:
        quarters/positions tracked, a breakdown of move kinds, total
        estimated profit across positions where it's computable, a simple
        conviction/activity tier, and the full move history for this filer.
        """
        self.get_object()  # 404s cleanly if the investor id doesn't exist
        data = Holding.objects.investor_profile(int(pk))
        data['moves'] = _iso_moves(data['moves'])
        return Response(data)


class HoldingViewSet(viewsets.ReadOnlyModelViewSet):
    """Raw holdings rows (static, one row per investor/security/quarter).
    Prefer /api/super-investors/moves/ for the action-oriented feed."""
    queryset = Holding.objects.select_related('investor')
    serializer_class = HoldingSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get('investor'):
            qs = qs.filter(investor_id=p['investor'])
        if p.get('ticker'):
            qs = qs.filter(ticker__iexact=p['ticker'])
        return qs


class MovesView(APIView):
    """GET /api/super-investors/moves/?investor=&ticker=&quarters=2&limit=50

    The core, action-oriented feed: recent notable holding CHANGES (new
    position / closed / increased X% / decreased X%) diffed against each
    filer's prior-quarter 13F, not a static holdings table. New positions
    and closes surface first, then the largest absolute % changes.
    """

    def get(self, request):
        p = request.query_params

        investor = p.get('investor')
        if investor and not str(investor).isdigit():
            raise ValidationError({'investor': 'Must be an integer investor id.'})

        try:
            quarters = int(p.get('quarters', 2))
        except (TypeError, ValueError):
            raise ValidationError({'quarters': 'Must be an integer.'})
        quarters = min(max(quarters, 1), 12)

        try:
            limit = int(p.get('limit', 50))
        except (TypeError, ValueError):
            raise ValidationError({'limit': 'Must be an integer.'})
        limit = min(max(limit, 1), 200)

        results = Holding.objects.moves(
            investor=int(investor) if investor else None,
            ticker=p.get('ticker'),
            quarters=quarters,
            limit=limit,
        )
        results = _iso_moves(results)

        return Response({'results': results, 'count': len(results), 'quarters': quarters})


class SuperInvestorsRouter(routers.DefaultRouter):
    def __init__(self):
        super().__init__()
        self.register('investors', SuperInvestorViewSet, basename='super-investor')
        self.register('holdings', HoldingViewSet, basename='holding')
