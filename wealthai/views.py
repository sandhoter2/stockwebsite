from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .engine import history_points, run_task
from .models import Holding, Portfolio, ReportTask
from .serializers import HoldingSerializer, PortfolioSerializer, ReportTaskSerializer


class PortfolioViewSet(viewsets.ModelViewSet):
    serializer_class = PortfolioSerializer

    def get_queryset(self):
        return (Portfolio.objects.filter(owner=self.request.user)
                .prefetch_related('holdings'))

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=['patch'], url_path='holdings')
    def upsert_holdings(self, request, pk=None):
        portfolio = self.get_object()
        items = request.data.get('holdings')
        if not isinstance(items, list) or not items:
            raise ValidationError({'holdings': 'Provide a non-empty list of holdings.'})
        for raw in items:
            ser = HoldingSerializer(data=raw)
            ser.is_valid(raise_exception=True)
            data = ser.validated_data
            Holding.objects.update_or_create(
                portfolio=portfolio, symbol=data['symbol'],
                defaults={'shares': data['shares'], 'cost_basis': data['cost_basis']})
        portfolio.refresh_from_db()
        return Response(PortfolioSerializer(portfolio).data)

    @action(detail=True, methods=['get'], url_path='history')
    def history(self, request, pk=None):
        portfolio = self.get_object()
        raw = request.query_params.get('days', 90)
        try:
            days = int(raw)
        except (TypeError, ValueError):
            raise ValidationError({'days': 'Must be an integer.'})
        return Response(history_points(portfolio, days=days))

    @action(detail=True, methods=['post'], url_path='report')
    def report(self, request, pk=None):
        portfolio = self.get_object()
        if not portfolio.holdings.exists():
            raise ValidationError({'holdings': 'Add holdings before generating a report.'})
        provider = request.data.get('provider') or 'auto'
        if provider not in {c[0] for c in ReportTask.PROVIDER_CHOICES}:
            raise ValidationError({'provider': 'Unknown provider.'})
        fmt = request.data.get('format') or 'markdown'
        if fmt not in {c[0] for c in ReportTask.FORMAT_CHOICES}:
            raise ValidationError({'format': 'Unknown format.'})
        task = ReportTask.objects.create(
            portfolio=portfolio, owner=request.user,
            provider=provider, output_format=fmt, status='queued')
        task.append_log('queued', 'Waiting to run')
        return Response(ReportTaskSerializer(task).data, status=status.HTTP_201_CREATED)


class ReportTaskViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ReportTaskSerializer

    def get_queryset(self):
        return ReportTask.objects.filter(owner=self.request.user).select_related('portfolio')

    @action(detail=True, methods=['post'], url_path='run')
    def run(self, request, pk=None):
        task = self.get_object()
        if task.status in ('queued', 'failed'):
            task = run_task(task)
        return Response(ReportTaskSerializer(task).data)
