from django.contrib import admin

from .models import MarketReport


@admin.register(MarketReport)
class MarketReportAdmin(admin.ModelAdmin):
    list_display = ('published_date', 'firm', 'report_type', 'title', 'fetched_at')
    list_filter = ('firm', 'report_type')
    search_fields = ('title', 'short_summary', 'source_url')
    date_hierarchy = 'published_date'
