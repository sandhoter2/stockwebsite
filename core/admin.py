from django.contrib import admin

from core.models import HealthIssue, JobRun


@admin.register(JobRun)
class JobRunAdmin(admin.ModelAdmin):
    list_display = ['name', 'status', 'finished_at', 'duration_seconds']
    list_filter = ['name', 'status']
    ordering = ['-finished_at']


@admin.register(HealthIssue)
class HealthIssueAdmin(admin.ModelAdmin):
    list_display = ['kind', 'severity', 'is_open', 'detected_at', 'last_seen_at']
    list_filter = ['severity', 'kind']
    ordering = ['-last_seen_at']
