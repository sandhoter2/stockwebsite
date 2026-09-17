from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from core.models import HealthIssue, JobRun


@never_cache
@login_required
def dashboard(request):
    """React SPA: trade dashboard (login enforced by @login_required)."""
    return render(request, 'dashboard.html')


@never_cache
def login_page(request):
    """React SPA: login screen. Already-authenticated users go to the app."""
    if request.user.is_authenticated:
        return redirect('/')
    return render(request, 'login.html')


def healthz(request):
    """ngrok/liveness probe — public, no auth."""
    return JsonResponse({'status': 'ok'})


@never_cache
@staff_member_required
def ktl_dashboard(request):
    """KTL (keep-the-lights-on) ops dashboard — staff-only, separate page
    from the customer-facing SPA. Cron job health + open data-integrity
    tickets, both populated by scripts/daily_*.sh via ktl_record and the
    ktl_health_check management command."""
    job_names = JobRun.objects.values_list('name', flat=True).distinct()
    jobs = [JobRun.objects.filter(name=n).order_by('-finished_at').first() for n in job_names]
    open_issues = HealthIssue.objects.filter(resolved_at__isnull=True)
    resolved_issues = HealthIssue.objects.filter(resolved_at__isnull=False)[:20]
    return render(request, 'ktl.html', {
        'jobs': jobs,
        'open_issues': open_issues,
        'resolved_issues': resolved_issues,
    })


@require_POST
@staff_member_required
def ktl_resolve_issue(request, issue_id):
    from django.shortcuts import get_object_or_404
    from django.utils import timezone
    issue = get_object_or_404(HealthIssue, id=issue_id, resolved_at__isnull=True)
    issue.resolved_at = timezone.now()
    issue.resolved_by = request.user
    issue.save(update_fields=['resolved_at', 'resolved_by'])
    return redirect('ktl-dashboard')
