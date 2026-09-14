"""Create paper-trading users + preferences (idempotent).

Adds the requested consumers-as-users (admin already exists) and gives each a
UserPreference with auto_paper on and the top-10 leaderboard channels as their
default auto-trade set. Passwords are a documented default to be changed.

  manage.py seed_users [--password X]
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db.models import Sum

from traderacker.models import Channel, UserPreference

DEFAULT_USERS = [
    ('vijay35', 'vijay.tibco35@gmail.com'),
    ('vijay34', 'vijay.tibco34@gmail.com'),
]


class Command(BaseCommand):
    help = 'Create paper-trading users and seed their preferences.'

    def add_arguments(self, parser):
        parser.add_argument('--password', default='papertrade123')

    def handle(self, *args, **opts):
        top = list(Channel.objects.annotate(r=Sum('trades__realized'))
                   .order_by('-r')[:10])
        made = 0
        for username, email in DEFAULT_USERS:
            u, created = User.objects.get_or_create(
                username=username,
                defaults={'email': email, 'is_staff': True})
            if created:
                u.set_password(opts['password'])
                u.save()
                made += 1
            pref = UserPreference.for_user(u)
            if not pref.auto_consumers.exists():
                pref.auto_consumers.set(top)
        # ensure admin has prefs + auto consumers too
        admin = User.objects.filter(username='admin').first()
        if admin:
            pref = UserPreference.for_user(admin)
            if not pref.auto_consumers.exists():
                pref.auto_consumers.set(top)
        self.stdout.write(self.style.SUCCESS(
            f'Users created: {made} · total paper users: '
            f'{User.objects.count()} · default password: {opts["password"]}'))
