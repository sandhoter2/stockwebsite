"""URL configuration for the trade tracker project."""
from django.contrib import admin
from django.urls import include, path

from core import views as core_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', core_views.dashboard, name='dashboard'),
    path('login/', core_views.login_page, name='login'),
    path('healthz/', core_views.healthz, name='healthz'),
    path('api/auth/', include('accounts.urls')),
    path('api/tracker/', include('traderacker.urls')),
    path('api/congress/', include('congress_trades.urls')),
    path('api/institutional/', include('institutional_reports.urls')),
    path('api/news/', include('market_news.urls')),
    path('api/super-investors/', include('super_investors.urls')),
]
