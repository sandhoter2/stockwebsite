from rest_framework import serializers

from .models import Holding, Portfolio, ReportTask


class HoldingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Holding
        fields = ['id', 'symbol', 'shares', 'cost_basis', 'updated_at']
        read_only_fields = ['id', 'updated_at']

    def validate_symbol(self, value):
        value = (value or '').upper().strip()
        if not value:
            raise serializers.ValidationError('Symbol is required.')
        return value


class PortfolioSerializer(serializers.ModelSerializer):
    holdings = HoldingSerializer(many=True, read_only=True)
    holdings_count = serializers.IntegerField(source='holdings.count', read_only=True)

    class Meta:
        model = Portfolio
        fields = ['id', 'name', 'description', 'created_at', 'updated_at',
                  'holdings', 'holdings_count']
        read_only_fields = ['id', 'created_at', 'updated_at']


class ReportTaskSerializer(serializers.ModelSerializer):
    portfolio_name = serializers.CharField(source='portfolio.name', read_only=True)

    class Meta:
        model = ReportTask
        fields = ['id', 'portfolio', 'portfolio_name', 'status', 'provider', 'model',
                  'output_format', 'markdown', 'payload', 'metrics', 'log', 'error',
                  'created_at', 'started_at', 'finished_at']
        read_only_fields = ['id', 'portfolio', 'portfolio_name', 'status', 'model',
                            'markdown', 'payload', 'metrics', 'log', 'error',
                            'created_at', 'started_at', 'finished_at']
