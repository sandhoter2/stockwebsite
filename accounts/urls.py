from django.urls import path

from .views import LoginAPI, LogoutAPI, MeAPI

urlpatterns = [
    path('login/', LoginAPI.as_view(), name='api-login'),
    path('logout/', LogoutAPI.as_view(), name='api-logout'),
    path('me/', MeAPI.as_view(), name='api-me'),
]
