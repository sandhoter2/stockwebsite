from django.contrib import admin

from .models import CongressTrade


@admin.register(CongressTrade)
class CongressTradeAdmin(admin.ModelAdmin):
    list_display = ('disclosure_date', 'transaction_date', 'politician_name', 'party',
                    'chamber', 'ticker', 'transaction_type', 'amount_min', 'amount_max')
    list_filter = ('chamber', 'party', 'transaction_type')
    search_fields = ('politician_name', 'ticker', 'asset_description')
    date_hierarchy = 'disclosure_date'
