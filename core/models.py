from django.db import models


class JobRun(models.Model):
    """One execution of a scheduled ops job (the daily_*.sh cron scripts),
    recorded by the `ktl_record` management command those scripts call as
    their last step. Powers the KTL (keep-the-lights-on) admin dashboard's
    cron-health view."""
    STATUS_CHOICES = [('ok', 'OK'), ('failed', 'Failed')]

    name = models.CharField(max_length=64, db_index=True,
        help_text="Job identifier, e.g. 'telegram_sync', 'super_investors', 'poll_market'")
    status = models.CharField(max_length=8, choices=STATUS_CHOICES)
    detail = models.TextField(blank=True, help_text="Short human-readable summary of the run")
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()

    class Meta:
        ordering = ['-finished_at']

    def __str__(self):
        return f"{self.name}: {self.status} @ {self.finished_at}"

    @property
    def duration_seconds(self):
        return round((self.finished_at - self.started_at).total_seconds(), 1)


class HealthIssue(models.Model):
    """A detected data/ops problem, created or refreshed by `ktl_health_check`.
    Admin-only ticket list -- resolving one is a manual acknowledgement, not
    an automatic re-check (the next health_check run will re-open it if the
    underlying problem is still there)."""
    SEVERITY_CHOICES = [('warning', 'Warning'), ('critical', 'Critical')]

    kind = models.CharField(max_length=64, db_index=True,
        help_text="Stable machine key for the check, e.g. 'stale_telegram_data'")
    severity = models.CharField(max_length=8, choices=SEVERITY_CHOICES, default='warning')
    message = models.TextField()
    detected_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ['-severity', '-last_seen_at']

    def __str__(self):
        return f"[{self.severity}] {self.kind}"

    @property
    def is_open(self):
        return self.resolved_at is None
