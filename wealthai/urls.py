from rest_framework import routers

from .views import PortfolioViewSet, ReportTaskViewSet

router = routers.DefaultRouter()
router.register('portfolios', PortfolioViewSet, basename='wealth-portfolio')
router.register('tasks', ReportTaskViewSet, basename='wealth-task')

urlpatterns = router.urls
