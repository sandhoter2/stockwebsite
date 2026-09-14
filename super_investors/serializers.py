from rest_framework import serializers

from .models import Holding, SuperInvestor


class SuperInvestorSerializer(serializers.ModelSerializer):
    short_label = serializers.CharField(read_only=True)

    class Meta:
        model = SuperInvestor
        fields = ['id', 'name', 'fund_name', 'cik', 'is_active', 'short_label']


class HoldingSerializer(serializers.ModelSerializer):
    """Static holdings-row shape (used by the admin-style list, not the
    action-oriented /moves/ feed which builds its own dict)."""
    investor_name = serializers.CharField(source='investor.name', read_only=True)
    investor_short_label = serializers.CharField(source='investor.short_label', read_only=True)
    display_symbol = serializers.CharField(read_only=True)
    change_summary_line = serializers.CharField(read_only=True)
    change_kind = serializers.CharField(read_only=True)
    change_pct = serializers.FloatField(read_only=True)

    class Meta:
        model = Holding
        fields = ['id', 'investor', 'investor_name', 'investor_short_label',
                  'cusip', 'issuer_name', 'ticker', 'display_symbol',
                  'shares', 'market_value', 'filing_quarter', 'filed_date',
                  'accession_number', 'change_summary_line', 'change_kind',
                  'change_pct']
