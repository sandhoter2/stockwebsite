from rest_framework import routers

from .views import MarketReportViewSet

router = routers.DefaultRouter()
router.register('reports', MarketReportViewSet, basename='market-report')

urlpatterns = router.urls
