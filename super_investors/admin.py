from django.contrib import admin

from .models import Holding, SuperInvestor


@admin.register(SuperInvestor)
class SuperInvestorAdmin(admin.ModelAdmin):
    list_display = ['name', 'fund_name', 'cik', 'is_active', 'created_at']
    search_fields = ['name', 'fund_name', 'cik']
    list_filter = ['is_active']


@admin.register(Holding)
class HoldingAdmin(admin.ModelAdmin):
    list_display = ['investor', 'ticker', 'issuer_name', 'shares', 'market_value',
                    'filing_quarter', 'filed_date']
    search_fields = ['ticker', 'issuer_name', 'cusip']
    list_filter = ['investor', 'filing_quarter']
    date_hierarchy = 'filing_quarter'
