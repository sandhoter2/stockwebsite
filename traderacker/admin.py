from django.contrib import admin

from .models import (Channel, PaperTrade, QuantityRule, Quote, TelegramMessage,
                     Trade, UserPreference)


class TradeInline(admin.TabularInline):
    model = Trade
    extra = 0
    fields = ('date', 'trade', 'direction', 'entry', 'target', 'stop_loss',
              'ltp_exit', 'realized', 'status')


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ('name', 'peer', 'style', 'trades_count', 'is_active')
    search_fields = ('name', 'peer')
    list_editable = ('style',)
    inlines = [TradeInline]

    @admin.display(description='Trades')
    def trades_count(self, obj):
        return obj.trades.count()


@admin.register(UserPreference)
class UserPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'auto_paper', 'capital_per_trade',
                    'stop_loss_pct', 'trailing_pct')
    filter_horizontal = ('auto_consumers',)


@admin.register(PaperTrade)
class PaperTradeAdmin(admin.ModelAdmin):
    list_display = ('user', 'symbol', 'side', 'asset_class', 'entry_price',
                    'current_price', 'realized_pct', 'status', 'price_source')
    list_filter = ('status', 'asset_class', 'user', 'side')
    search_fields = ('symbol', 'user__username')
    readonly_fields = ('realized_pct', 'realized_inr', 'accuracy', 'closed_at')


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display = ('date', 'channel', 'trade', 'direction', 'entry',
                    'ltp_exit', 'realized', 'status')
    list_filter = ('status', 'channel')
    search_fields = ('trade', 'note', 'channel__name')
    date_hierarchy = 'date'


@admin.register(Quote)
class QuoteAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'channel', 'kind', 'ltp', 'asof')
    search_fields = ('symbol',)


@admin.register(QuantityRule)
class QuantityRuleAdmin(admin.ModelAdmin):
    list_display = ('scope', 'key', 'qty')


@admin.register(TelegramMessage)
class TelegramMessageAdmin(admin.ModelAdmin):
    list_display = ('channel', 'mid', 'ts', 'preview')
    search_fields = ('text',)

    @admin.display(description='Text')
    def preview(self, obj):
        return (obj.text[:80] + '…') if len(obj.text) > 80 else obj.text
