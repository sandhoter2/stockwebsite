import uuid

from django.db import models
from django.utils import timezone


class Portfolio(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='portfolios')
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class Holding(models.Model):
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name='holdings')
    symbol = models.CharField(max_length=16)
    shares = models.FloatField()
    cost_basis = models.FloatField(help_text="Average cost per share")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['symbol']
        constraints = [
            models.UniqueConstraint(fields=['portfolio', 'symbol'], name='uniq_portfolio_symbol'),
        ]

    def __str__(self):
        return f"{self.symbol} x {self.shares}"

    @property
    def cost_value(self):
        return round((self.shares or 0) * (self.cost_basis or 0), 2)


class ReportTask(models.Model):
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
    ]
    PROVIDER_CHOICES = [
        ('auto', 'Auto (Groq short / OpenAI rich)'),
        ('groq', 'Groq via OmniRoute'),
        ('openai', 'OpenAI via OmniRoute'),
    ]
    FORMAT_CHOICES = [
        ('markdown', 'Markdown'),
        ('json', 'JSON'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    portfolio = models.ForeignKey(Portfolio, on_delete=models.CASCADE, related_name='tasks')
    owner = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='wealth_tasks')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='queued', db_index=True)
    provider = models.CharField(max_length=12, choices=PROVIDER_CHOICES, default='auto')
    model = models.CharField(max_length=64, blank=True)
    output_format = models.CharField(max_length=12, choices=FORMAT_CHOICES, default='markdown')
    markdown = models.TextField(blank=True)
    payload = models.JSONField(null=True, blank=True)
    metrics = models.JSONField(null=True, blank=True)
    log = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.portfolio.name} {self.status}"

    def append_log(self, step, message):
        rows = list(self.log or [])
        rows.append({
            'ts': timezone.now().isoformat(),
            'step': step,
            'message': message,
        })
        self.log = rows
        self.save(update_fields=['log'])
