from rest_framework import serializers

from .models import (Channel, PaperTrade, QuantityRule, Quote, TelegramMessage,
                     Trade, UserPreference, Watchlist)


def _now_ist():
    from django.utils import timezone as tz
    return tz.localtime(tz.now())


def _today_ist():
    return _now_ist().date()


class ChannelSerializer(serializers.ModelSerializer):
    trades_count = serializers.IntegerField(read_only=True)
    open_count = serializers.IntegerField(read_only=True)
    realized_total = serializers.FloatField(read_only=True, allow_null=True)
    unrealized_total = serializers.FloatField(read_only=True, allow_null=True)
    # invested_total = serializers.FloatField(read_only=True, allow_null=True)  # Removed
    wins = serializers.IntegerField(read_only=True, default=0)
    losses = serializers.IntegerField(read_only=True, default=0)
    booked = serializers.IntegerField(read_only=True, default=0)
    success_rate = serializers.SerializerMethodField()

    class Meta:
        model = Channel
        fields = ['id', 'peer', 'name', 'short', 'is_active',
                  'trades_count', 'open_count', 'realized_total',
                  'unrealized_total',
                  'wins', 'losses', 'booked', 'success_rate']

    def get_success_rate(self, obj):
        return round(100 * obj.wins / obj.booked, 1) if obj.booked else None


class TradeSerializer(serializers.ModelSerializer):
    channel_name = serializers.CharField(source='channel.short', read_only=True)
    pl_tag = serializers.ReadOnlyField()
    lot_size = serializers.ReadOnlyField()
    realized_total = serializers.ReadOnlyField()
    posted_ist = serializers.SerializerMethodField()
    sticker = serializers.SerializerMethodField()
    simple_direction = serializers.SerializerMethodField()
    # A missing date is invisible under any date-range filter (see
    # perform_create's fuller comment) -- these need a real DEFAULT AT THE
    # FIELD LEVEL, not just filled in later in perform_create(), because
    # Meta.validators' UniqueTogetherValidator (channel, date, trade, entry,
    # status) runs during is_valid(), BEFORE perform_create ever executes.
    # With date defaulting only in perform_create, the validator checked
    # uniqueness against date=None (never a real collision) while the
    # later actual INSERT used today's real date -- so two identical POSTs
    # both "validated" fine and the second crashed with an unhandled
    # IntegrityError (500) instead of the clean 400 the validator exists to
    # give. Live bug, reproduced via a real duplicate Postman POST.
    # `default=` (not `initial=`) only fires when the field is OMITTED from
    # a full create; DRF skips defaults entirely on a partial PATCH, so
    # perform_update's inline edits are unaffected.
    date = serializers.DateField(default=_today_ist, allow_null=True, required=False)
    posted_at = serializers.DateTimeField(default=_now_ist, allow_null=True, required=False)

    class Meta:
        model = Trade
        fields = ['id', 'channel', 'channel_name', 'date', 'posted_at', 'posted_ist',
                  'asset_class', 'strike', 'sticker', 'direction', 'simple_direction',
                  'trade', 'entry', 'target',
                  'stop_loss', 'ltp_exit', 'unrealized', 'realized',
                  'cumulative', 'status', 'note', 'manually_edited', 'pl_tag',
                  'lot_size', 'realized_total']
        read_only_fields = ['manually_edited']

    def get_posted_ist(self, obj):
        """Return posted_at in IST timezone (UTC+5:30)."""
        if not obj.posted_at:
            return None
        import pytz
        ist = pytz.timezone('Asia/Kolkata')
        return obj.posted_at.astimezone(ist).isoformat()

    def get_sticker(self, obj):
        """Extract base ticker symbol from trade string."""
        if not obj.trade:
            return ''
        return obj.trade.split()[0]

    def get_simple_direction(self, obj):
        """Simplify direction for UI: BUY/SELL or CALL/PUT."""
        if not obj.direction:
            return ''
        d = obj.direction.upper()
        if 'CALL' in d:
            return 'CALL'
        if 'PUT' in d:
            return 'PUT'
        if 'BUY' in d:
            return 'BUY'
        if 'SELL' in d:
            return 'SELL'
        return obj.direction


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
                  'profit_target_pct', 'max_hold_days',
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
                  'trailing_pct', 'profit_target_pct', 'max_hold_days',
                  'auto_consumers']


class WatchlistSerializer(serializers.ModelSerializer):
    channel_name = serializers.CharField(source='channel.short', read_only=True)

    class Meta:
        model = Watchlist
        fields = ['id', 'channel', 'channel_name', 'created_at']
        read_only_fields = ['id', 'channel_name', 'created_at']
