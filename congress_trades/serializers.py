from rest_framework import serializers

from .models import CongressTrade


class CongressTradeSerializer(serializers.ModelSerializer):
    """Row shape for the structured table: time | resource | stock |
    buy_or_sell | profit, plus the fields already used elsewhere
    (amount_range_label, summary_line, filing_url, ...).

    `time` is the transaction_date (when the member actually traded — the
    canonical "Time" column per product ask), with `disclosure_date` kept
    alongside since STOCK Act filings lag the real trade by weeks. `profit`
    is always an ESTIMATE (see congress_trades.market's docstring): a dollar
    figure derived from the disclosed amount range's midpoint and the
    ticker's real subsequent price move, never an exact P/L. `profit_kind`
    tells the frontend whether to label it "closed" (realized) or
    "estimated, still open" (unrealized) — and a blank value means we
    haven't been able to price it yet (e.g. a sale with no matching buy in
    our tracked window, or no market data for that ticker/date).
    """
    summary_line = serializers.ReadOnlyField()
    amount_range_label = serializers.ReadOnlyField()
    amount_mid = serializers.ReadOnlyField()
    profit = serializers.ReadOnlyField()
    profit_is_realized = serializers.ReadOnlyField()
    time = serializers.DateField(source='transaction_date', read_only=True)
    resource = serializers.SerializerMethodField()
    buy_or_sell = serializers.CharField(source='transaction_type', read_only=True)

    class Meta:
        model = CongressTrade
        fields = [
            'id', 'politician_name', 'party', 'chamber', 'state',
            'ticker', 'asset_description', 'transaction_type',
            'amount_min', 'amount_max', 'amount_range_label', 'amount_mid',
            'transaction_date', 'disclosure_date',
            'filing_url', 'source_doc_id', 'summary_line',
            # table-row shape
            'time', 'resource', 'buy_or_sell',
            'profit', 'profit_kind', 'profit_is_realized',
        ]

    def get_resource(self, obj):
        return f"{obj.politician_name} ({obj.party})" if obj.party != '?' else obj.politician_name


class PoliticianBreakdownSerializer(serializers.Serializer):
    """One leaderboard row per politician — same shape/spirit as
    traderacker's channel breakdown() output, just over closed round-trips
    of disclosed trades instead of paper trades."""
    politician_name = serializers.CharField()
    party = serializers.CharField()
    chamber = serializers.CharField()
    trades = serializers.IntegerField()
    buys = serializers.IntegerField()
    sells = serializers.IntegerField()
    closed = serializers.IntegerField()
    open = serializers.IntegerField()
    wins = serializers.IntegerField()
    losses = serializers.IntegerField()
    win_rate = serializers.FloatField(allow_null=True)
    confidence_score = serializers.FloatField(allow_null=True)
    realized_profit = serializers.FloatField(allow_null=True)
    unrealized_profit = serializers.FloatField(allow_null=True)
    tier = serializers.CharField()
    tier_label = serializers.CharField()
