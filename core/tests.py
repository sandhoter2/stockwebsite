import datetime as dt

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import HealthIssue, JobRun


class KtlRecordTests(TestCase):
    def test_records_ok_run(self):
        started = timezone.now().timestamp() - 5
        call_command('ktl_record', 'telegram_sync', str(started), '0', 'extract=0 import=0 parse=0')
        run = JobRun.objects.get(name='telegram_sync')
        self.assertEqual(run.status, 'ok')
        self.assertGreater(run.duration_seconds, 0)

    def test_records_failed_run(self):
        started = timezone.now().timestamp()
        call_command('ktl_record', 'poll_market', str(started), '1', 'crashed')
        run = JobRun.objects.get(name='poll_market')
        self.assertEqual(run.status, 'failed')
        self.assertIn('crashed', run.detail)


class KtlHealthCheckTests(TestCase):
    def test_opens_issue_for_stale_job(self):
        call_command('ktl_health_check')
        self.assertTrue(HealthIssue.objects.filter(
            kind='cron_stale_telegram_sync', resolved_at__isnull=True).exists())

    def test_resolves_issue_once_job_recorded_fresh(self):
        call_command('ktl_health_check')
        self.assertTrue(HealthIssue.objects.filter(
            kind='cron_stale_telegram_sync', resolved_at__isnull=True).exists())
        JobRun.objects.create(name='telegram_sync', status='ok', detail='',
                              started_at=timezone.now(), finished_at=timezone.now())
        call_command('ktl_health_check')
        self.assertFalse(HealthIssue.objects.filter(
            kind='cron_stale_telegram_sync', resolved_at__isnull=True).exists())

    def test_reopens_stale_cron_issue_after_resolve_if_still_stale(self):
        call_command('ktl_health_check')
        issue = HealthIssue.objects.get(kind='cron_stale_super_investors')
        issue.resolved_at = timezone.now()
        issue.save(update_fields=['resolved_at'])
        call_command('ktl_health_check')
        issue.refresh_from_db()
        self.assertIsNone(issue.resolved_at)

    def test_flags_failed_job_separately_from_staleness(self):
        JobRun.objects.create(name='poll_market', status='failed', detail='boom',
                              started_at=timezone.now(), finished_at=timezone.now())
        call_command('ktl_health_check')
        self.assertTrue(HealthIssue.objects.filter(
            kind='cron_failed_poll_market', resolved_at__isnull=True).exists())
        self.assertFalse(HealthIssue.objects.filter(
            kind='cron_stale_poll_market', resolved_at__isnull=True).exists())

    def test_no_data_quality_issue_when_trades_are_well_formed(self):
        from traderacker.models import Channel, Trade
        ch = Channel.objects.create(peer='-9', name='Ch', short='Ch')
        Trade.objects.create(channel=ch, trade='X', direction='BUY', entry=100,
                             stop_loss=90, target=110, status='Open',
                             asset_class='stock', source_mid=1)
        call_command('ktl_health_check')
        self.assertFalse(HealthIssue.objects.filter(
            kind='implausible_trade_levels', resolved_at__isnull=True).exists())

    def test_flags_implausible_trade_levels(self):
        from traderacker.models import Channel, Trade
        ch = Channel.objects.create(peer='-9', name='Ch', short='Ch')
        Trade.objects.create(channel=ch, trade='X', direction='BUY', entry=49500,
                             stop_loss=400, target=950, status='Open',
                             asset_class='stock', source_mid=1)
        call_command('ktl_health_check')
        self.assertTrue(HealthIssue.objects.filter(
            kind='implausible_trade_levels', resolved_at__isnull=True).exists())


class KtlDashboardAccessTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('staffer', password='pw12345!', is_staff=True)
        self.regular = User.objects.create_user('regular', password='pw12345!')

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(reverse('ktl-dashboard'))
        self.assertEqual(resp.status_code, 302)

    def test_non_staff_denied(self):
        self.client.login(username='regular', password='pw12345!')
        resp = self.client.get(reverse('ktl-dashboard'))
        self.assertEqual(resp.status_code, 302)

    def test_staff_can_view(self):
        self.client.login(username='staffer', password='pw12345!')
        resp = self.client.get(reverse('ktl-dashboard'))
        self.assertEqual(resp.status_code, 200)

    def test_staff_can_resolve_issue(self):
        issue = HealthIssue.objects.create(kind='test_issue', severity='warning', message='x')
        self.client.login(username='staffer', password='pw12345!')
        self.client.post(reverse('ktl-resolve-issue', args=[issue.id]))
        issue.refresh_from_db()
        self.assertIsNotNone(issue.resolved_at)
        self.assertEqual(issue.resolved_by, self.staff)

    def test_non_staff_cannot_resolve_issue(self):
        issue = HealthIssue.objects.create(kind='test_issue', severity='warning', message='x')
        self.client.login(username='regular', password='pw12345!')
        self.client.post(reverse('ktl-resolve-issue', args=[issue.id]))
        issue.refresh_from_db()
        self.assertIsNone(issue.resolved_at)
