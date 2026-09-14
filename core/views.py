from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache


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
