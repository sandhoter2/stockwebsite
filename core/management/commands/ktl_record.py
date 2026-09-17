"""Record one cron job execution for the KTL admin dashboard.

Called as the last step of each scripts/daily_*.sh -- wraps the job's own
exit code and a text summary into a JobRun row so the dashboard can show
"last run: ok/failed, N minutes ago" per job without scraping log files.

  manage.py ktl_record <name> <started_epoch> <exit_code> [detail text...]
"""
from datetime import datetime, timezone as dt_timezone

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import JobRun


class Command(BaseCommand):
    help = 'Record a cron job run (name, start epoch, exit code, detail) as a JobRun.'

    def add_arguments(self, parser):
        parser.add_argument('name')
        parser.add_argument('started_epoch', type=float)
        parser.add_argument('exit_code', type=int)
        parser.add_argument('detail', nargs='*', default=[])

    def handle(self, *args, **opts):
        started = datetime.fromtimestamp(opts['started_epoch'], tz=dt_timezone.utc)
        JobRun.objects.create(
            name=opts['name'],
            status='ok' if opts['exit_code'] == 0 else 'failed',
            detail=' '.join(opts['detail'])[:2000],
            started_at=started,
            finished_at=timezone.now(),
        )
        self.stdout.write(self.style.SUCCESS(f"ktl_record: {opts['name']} logged"))
