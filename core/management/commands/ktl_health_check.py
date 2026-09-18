"""Read-only data/ops sanity sweep for the KTL admin dashboard.

Each check below either resolves its HealthIssue (problem gone) or
creates/refreshes one (problem present) -- idempotent per `kind`, safe to
run daily via cron alongside the other scripts/daily_*.sh jobs. Deliberately
cheap and read-only: no parse_signals-style rebuild, just counts/timestamps.

  manage.py ktl_health_check
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import HealthIssue, JobRun
from traderacker.market_hours import is_market_open
from traderacker.models import Trade, TelegramMessage

STALE_TELEGRAM_HOURS = 30
STALE_JOB_HOURS = 30
CRON_JOBS = ['telegram_sync', 'super_investors', 'poll_market', 'market_news']
LIVE_SYNC_STALE_MINUTES = 10


class Command(BaseCommand):
    help = 'Run data/ops health checks and open or clear HealthIssue tickets.'

    def handle(self, *args, **opts):
        now = timezone.now()
        opened = closed = 0

        def upsert(kind, is_bad, severity, message):
            # Reopens the most recent issue of this kind if it recurs after
            # being manually resolved, rather than piling up duplicate rows
            # for the same ongoing problem every time this check runs.
            nonlocal opened, closed
            existing = HealthIssue.objects.filter(kind=kind).order_by('-last_seen_at').first()
            if is_bad:
                if existing:
                    existing.message = message
                    existing.severity = severity
                    was_resolved = existing.resolved_at is not None
                    existing.resolved_at = None
                    existing.save(update_fields=['message', 'severity', 'last_seen_at', 'resolved_at'])
                    if was_resolved:
                        opened += 1
                else:
                    HealthIssue.objects.create(kind=kind, severity=severity, message=message)
                    opened += 1
            elif existing and existing.resolved_at is None:
                existing.resolved_at = now
                existing.save(update_fields=['resolved_at'])
                closed += 1

        # 1. Telegram data freshness
        latest_msg = TelegramMessage.objects.order_by('-ts').values_list('ts', flat=True).first()
        stale = latest_msg is None or (now - latest_msg).total_seconds() > STALE_TELEGRAM_HOURS * 3600
        upsert('stale_telegram_data', stale, 'critical',
               f"Latest Telegram message is from {latest_msg} ({STALE_TELEGRAM_HOURS}h+ old) "
               "-- daily_telegram_sync.sh may not be running." if stale else '')

        # 2. Each cron job: did it run recently, and did it succeed last time?
        for job in CRON_JOBS:
            last = JobRun.objects.filter(name=job).order_by('-finished_at').first()
            missing_or_stale = last is None or (now - last.finished_at).total_seconds() > STALE_JOB_HOURS * 3600
            upsert(f'cron_stale_{job}', missing_or_stale, 'critical',
                   (f"No JobRun recorded for '{job}' yet." if last is None
                    else f"Last '{job}' run was {last.finished_at} ({STALE_JOB_HOURS}h+ ago).") if missing_or_stale else '')
            failed = last is not None and last.status == 'failed'
            upsert(f'cron_failed_{job}', failed, 'critical',
                   f"Last '{job}' run failed at {last.finished_at}: {last.detail}" if failed else '')

        # 3. Live intraday sync (scripts/live_market_sync.sh, every 2 min
        # during NSE hours) -- only meaningful to check *while the market is
        # open*; outside hours the cron script no-ops on purpose and records
        # nothing, so this must not fire a false "stale" alert overnight.
        if is_market_open():
            last_live = JobRun.objects.filter(name='live_market_sync').order_by('-finished_at').first()
            stale_live = (last_live is None or
                          (now - last_live.finished_at).total_seconds() > LIVE_SYNC_STALE_MINUTES * 60)
            upsert('live_sync_stale_during_market_hours', stale_live, 'critical',
                   (f"No live_market_sync run in the last {LIVE_SYNC_STALE_MINUTES} min while NSE is open "
                    f"-- last run was {last_live.finished_at if last_live else 'never'}.") if stale_live else '')
        else:
            upsert('live_sync_stale_during_market_hours', False, 'critical', '')

        # 4. Implausible open-trade data (entry/SL/target structurally wrong for direction)
        bad = 0
        for t in Trade.objects.filter(status='Open').exclude(asset_class='option').filter(entry__isnull=False):
            is_buy = (t.direction or '').upper() in Trade.BUY_DIRECTIONS
            if is_buy:
                if (t.stop_loss is not None and t.stop_loss >= t.entry) or (t.target is not None and t.target <= t.entry):
                    bad += 1
            else:
                if (t.stop_loss is not None and t.stop_loss <= t.entry) or (t.target is not None and t.target >= t.entry):
                    bad += 1
        upsert('implausible_trade_levels', bad > 0, 'warning',
               f"{bad} open trade(s) have a stop_loss/target on the wrong side of entry for their "
               "direction -- likely a parser artifact (e.g. 'points from entry' stored as an absolute "
               "level). These are already excluded from auto-close (Trade.mark_live) but the source "
               "data is still wrong." if bad else '')

        self.stdout.write(self.style.SUCCESS(f'ktl_health_check: {opened} opened · {closed} closed'))
