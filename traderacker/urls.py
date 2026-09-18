from django.urls import include, path

from .views import (BreakdownView, ChannelStatsView, EventsView, PicksView,
                    PrefsView, SummaryView, TodaysCallsView, TrackerRouter,
                    TradesExportView)

router = TrackerRouter()

urlpatterns = [
    path('summary/', SummaryView.as_view(), name='tracker-summary'),
    path('stats/breakdown/', BreakdownView.as_view(), name='tracker-breakdown'),
    path('stats/', ChannelStatsView.as_view(), name='tracker-stats'),
    path('picks/', PicksView.as_view(), name='tracker-picks'),
    path('calls/', TodaysCallsView.as_view(), name='tracker-calls'),
    path('events/', EventsView.as_view(), name='tracker-events'),
    path('trades/export/', TradesExportView.as_view(), name='tracker-trades-export'),
    path('prefs/', PrefsView.as_view(), name='tracker-prefs'),
    path('', include(router.urls)),
]
