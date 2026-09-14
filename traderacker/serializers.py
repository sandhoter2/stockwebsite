from rest_framework import serializers

from .models import (Channel, PaperTrade, QuantityRule, Quote, TelegramMessage,
                     Trade, UserPreference)


class ChannelSerializer(serializers.ModelSerializer):
    trades_count = serializers.IntegerField(read_only=True)
    open_count = serializers.IntegerField(read_only=True)
    realized_total = serializers.FloatField(read_only=True, allow_null=True)
    unrealized_total = serializers.FloatField(read_only=True, allow_null=True)
    invested_total = serializers.FloatField(read_only=True, allow_null=True)
    wins = serializers.IntegerField(read_only=True, default=0)
    losses = serializers.IntegerField(read_only=True, default=0)
    booked = serializers.IntegerField(read_only=True, default=0)
    success_rate = serializers.SerializerMethodField()

    class Meta:
        model = Channel
        fields = ['id', 'peer', 'name', 'short', 'is_active',
                  'trades_count', 'open_count', 'realized_total',
                  'unrealized_total', 'invested_total',
                  'wins', 'losses', 'booked', 'success_rate']

    def get_success_rate(self, obj):
        return round(100 * obj.wins / obj.booked, 1) if obj.booked else None


class TradeSerializer(serializers.ModelSerializer):
    channel_name = serializers.CharField(source='channel.short', read_only=True)

    class Meta:
        model = Trade
        fields = ['id', 'channel', 'channel_name', 'date', 'posted_at',
                  'asset_class', 'trade', 'direction', 'entry', 'target',
                  'stop_loss', 'ltp_exit', 'unrealized', 'realized',
                  'cumulative', 'status', 'note']


class QuoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Quote
        fields = ['id', 'channel', 'symbol', 'name', 'kind', 'ltp', 'asof']


class QuantityRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuantityRule
        fields = ['id', 'scope', 'key', 'qty']


class TelegramMessageSerializer(serializers.ModelSerializer):
    channel_name = serializers.CharField(source='channel.short', read_only=True)

    class Meta:
        model = TelegramMessage
        fields = ['id', 'channel', 'channel_name', 'mid', 'day_label', 'text', 'ts']


class PaperTradeSerializer(serializers.ModelSerializer):
    unrealized_pct = serializers.FloatField(read_only=True)
    unrealized_inr = serializers.FloatField(read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = PaperTrade
        fields = ['id', 'username', 'symbol', 'asset_class', 'side',
                  'notional_inr', 'entry_price', 'price_source', 'current_price',
                  'highest_price', 'lowest_price', 'stop_loss_pct', 'trailing_pct',
                  'status', 'opened_at', 'closed_at', 'exit_price',
                  'realized_pct', 'realized_inr', 'unrealized_pct',
                  'unrealized_inr', 'accuracy', 'is_manual', 'notes',
                  'source_trade']
        read_only_fields = ['id', 'username', 'opened_at', 'closed_at',
                            'realized_pct', 'realized_inr', 'accuracy',
                            'highest_price', 'lowest_price', 'current_price']

    def get_unrealized_pct(self, obj):
        return obj.unrealized_pct()

    def get_unrealized_inr(self, obj):
        return obj.unrealized_inr()


class UserPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPreference
        fields = ['auto_paper', 'capital_per_trade', 'stop_loss_pct',
                  'trailing_pct', 'auto_consumers']
