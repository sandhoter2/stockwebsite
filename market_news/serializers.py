from rest_framework import serializers

from .models import NewsItem


class NewsItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = NewsItem
        fields = ['id', 'ticker', 'headline_line', 'sentiment', 'sentiment_score',
                 'relevance_score', 'source', 'source_url', 'published_at',
                 'fetched_at']
