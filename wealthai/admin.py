from django.contrib import admin

from .models import Holding, Portfolio, ReportTask


class HoldingInline(admin.TabularInline):
    model = Holding
    extra = 0


@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'created_at')
    inlines = [HoldingInline]


@admin.register(ReportTask)
class ReportTaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'portfolio', 'owner', 'status', 'provider', 'created_at')
    list_filter = ('status', 'provider')
