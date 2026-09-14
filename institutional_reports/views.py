from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

from .models import MarketReport
from .serializers import MarketReportSerializer


class MarketReportViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/institutional/reports/?firm=&type=&days=90
    Recent public market-outlook/commentary items, terse (title + short
    summary + source link), sorted newest first."""
    queryset = MarketReport.objects.all()
    serializer_class = MarketReportSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params

        firm = p.get('firm')
        if firm:
            valid_firms = {c[0] for c in MarketReport.FIRM_CHOICES}
            if firm not in valid_firms:
                raise ValidationError({'firm': 'Unknown firm: ' + firm})
            qs = qs.firm(firm)

        report_type = p.get('type')
        if report_type:
            valid_types = {c[0] for c in MarketReport.TYPE_CHOICES}
            if report_type not in valid_types:
                raise ValidationError({'type': 'Unknown type: ' + report_type})
            qs = qs.report_type(report_type)

        days = p.get('days')
        if days:
            try:
                days = int(days)
            except ValueError:
                raise ValidationError({'days': 'Must be an integer.'})
            qs = qs.within_days(days)

        return qs.recent_first()
