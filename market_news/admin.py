from django.contrib import admin

from .models import NewsItem


@admin.register(NewsItem)
class NewsItemAdmin(admin.ModelAdmin):
    list_display = ('ticker', 'headline_line', 'sentiment', 'relevance_score',
                    'source', 'published_at')
    list_filter = ('sentiment', 'source')
    search_fields = ('ticker', 'headline_line', 'source')
    date_hierarchy = 'published_at'
