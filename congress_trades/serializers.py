from rest_framework import serializers

from .models import CongressTrade


class CongressTradeSerializer(serializers.ModelSerializer):
    summary_line = serializers.ReadOnlyField()
    amount_range_label = serializers.ReadOnlyField()

    class Meta:
        model = CongressTrade
        fields = [
            'id', 'politician_name', 'party', 'chamber', 'state',
            'ticker', 'asset_description', 'transaction_type',
            'amount_min', 'amount_max', 'amount_range_label',
            'transaction_date', 'disclosure_date',
            'filing_url', 'source_doc_id', 'summary_line',
        ]
