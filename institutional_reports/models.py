from django.db import models


class MarketReportQuerySet(models.QuerySet):
    """Fat-queryset filters used by the REST view (thin controller)."""

    def firm(self, firm):
        if not firm:
            return self
        return self.filter(firm=firm)

    def report_type(self, report_type):
        if not report_type:
            return self
        return self.filter(report_type=report_type)

    def within_days(self, days):
        if not days:
            return self
        from datetime import timedelta

        from django.utils import timezone
        cutoff = timezone.now().date() - timedelta(days=days)
        return self.filter(published_date__gte=cutoff)

    def recent_first(self):
        return self.order_by('-published_date', '-fetched_at')


class MarketReport(models.Model):
    """A single public market-outlook/research item from an institutional
    source (BlackRock, JPMorgan, …). Deliberately terse: we store a short
    extracted takeaway, not the full article — the source_url is the
    click-through for the complete piece (both for product focus and to
    avoid reproducing publishers' content wholesale)."""

    FIRM_BLACKROCK = 'blackrock'
    FIRM_JPMORGAN = 'jpmorgan'
    FIRM_CHOICES = [
        (FIRM_BLACKROCK, 'BlackRock'),
        (FIRM_JPMORGAN, 'JPMorgan'),
    ]

    TYPE_QUARTERLY_OUTLOOK = 'quarterly_outlook'
    TYPE_YEARLY_FORECAST = 'yearly_forecast'
    TYPE_WEEKLY_COMMENTARY = 'weekly_commentary'
    TYPE_RESEARCH_NOTE = 'research_note'
    TYPE_CHOICES = [
        (TYPE_QUARTERLY_OUTLOOK, 'Quarterly outlook'),
        (TYPE_YEARLY_FORECAST, 'Yearly forecast'),
        (TYPE_WEEKLY_COMMENTARY, 'Weekly commentary'),
        (TYPE_RESEARCH_NOTE, 'Research note'),
    ]

    firm = models.CharField(max_length=16, choices=FIRM_CHOICES)
    title = models.CharField(max_length=500)
    published_date = models.DateField(help_text="Date the source published the piece")
    report_type = models.CharField(max_length=24, choices=TYPE_CHOICES,
                                   default=TYPE_RESEARCH_NOTE)
    short_summary = models.TextField(
        blank=True,
        help_text="A few-sentence extracted takeaway (deck/subheading or "
                  "first substantive paragraph) — not the full article.")
    source_url = models.URLField(max_length=1000, unique=True,
                                 help_text="Canonical link to the full piece; dedupe key.")
    fetched_at = models.DateTimeField(auto_now=True,
                                      help_text="When our scraper last pulled/updated this row.")

    objects = MarketReportQuerySet.as_manager()

    class Meta:
        ordering = ['-published_date', '-fetched_at']

    def __str__(self):
        return f'[{self.get_firm_display()}] {self.title}'
