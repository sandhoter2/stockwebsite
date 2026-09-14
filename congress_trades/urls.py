from django.urls import include, path

from .views import CongressRouter

router = CongressRouter()

urlpatterns = [
    path('', include(router.urls)),
]
