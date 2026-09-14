from datetime import timedelta

from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import NewsItem
from .serializers import NewsItemSerializer


class NewsFeedView(APIView):
    """GET /api/news/feed/[?ticker=AMD&min_relevance=0.5&days=3]

    Curated, action-oriented news feed — terse per-ticker lines only (see
    NewsItem docstring), most relevant/recent first. Not a raw headline dump.
    """

    def get(self, request):
        p = request.query_params

        min_relevance = p.get('min_relevance', 0.5)
        try:
            min_relevance = float(min_relevance)
        except (TypeError, ValueError):
            raise ValidationError({'min_relevance': 'Must be a number.'})

        raw_days = p.get('days', 3)
        try:
            days = int(raw_days)
        except (TypeError, ValueError):
            raise ValidationError({'days': 'Must be an integer.'})
        days = min(max(days, 1), 90)

        qs = (NewsItem.objects
              .for_ticker(p.get('ticker'))
              .min_relevance(min_relevance)
              .recent(timezone.now() - timedelta(days=days))
              .order_by('-relevance_score', '-published_at'))

        limit = min(int(p.get('limit', 50) or 50), 200)
        results = NewsItemSerializer(qs[:limit], many=True).data
        return Response({'results': results, 'count': len(results)})
