from rest_framework import serializers

from .models import MarketReport


class MarketReportSerializer(serializers.ModelSerializer):
    firm_display = serializers.CharField(source='get_firm_display', read_only=True)
    report_type_display = serializers.CharField(source='get_report_type_display', read_only=True)

    class Meta:
        model = MarketReport
        fields = ['id', 'firm', 'firm_display', 'title', 'published_date',
                  'report_type', 'report_type_display', 'short_summary',
                  'source_url', 'fetched_at']
