from django.urls import include, path

from .views import MovesView, SuperInvestorsRouter

router = SuperInvestorsRouter()

urlpatterns = [
    path('moves/', MovesView.as_view(), name='super-investors-moves'),
    path('', include(router.urls)),
]
