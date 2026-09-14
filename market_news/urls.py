from django.urls import path

from .views import NewsFeedView

urlpatterns = [
    path('feed/', NewsFeedView.as_view(), name='market-news-feed'),
]
