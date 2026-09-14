"""Import data from the legacy telegram-trade-tracker folder into the DB.

Reads: groups.json, ledger.xlsx, market.json, quantities.json, states/*.json
Idempotent: upserts by unique keys, safe to re-run after each poller cycle.
"""
import datetime as dt
import glob
import json
import os
import re

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone as dj_timezone
from django.utils.dateparse import parse_datetime

from traderacker.models import Channel, QuantityRule, Quote, TelegramMessage, Trade


def norm_status(raw):
    if not raw:
        return 'Open'
    r = str(raw)
    if r.startswith('Closed'):
        return 'Closed'
    return 'Open'


def as_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def as_date(v):
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


# legacy market.json 'asof' strings look like "2026-09-13 00:12 IST" (a plain
# timestamp in the app's configured TIME_ZONE, with a trailing tz label that
# isn't a parseable tz abbreviation on its own) or occasionally an ISO string.
_ASOF_TZ_SUFFIX = re.compile(r'\s+[A-Za-z]{2,5}$')


def as_asof_datetime(v):
    """Best-effort parse of a legacy 'asof' value into an aware datetime.

    Returns None (never raises) for empty/unparseable values so a handful of
    garbage rows never abort the whole import.
    """
    if v is None or v == '':
        return None
    if isinstance(v, dt.datetime):
        return dj_timezone.make_aware(v) if dj_timezone.is_naive(v) else v
    s = str(v).strip()
    if not s:
        return None
    parsed = parse_datetime(s)
    if parsed is None:
        # strip a trailing tz label ("IST", "UTC", ...) that parse_datetime
        # can't handle, and parse the remaining naive timestamp
        stripped = _ASOF_TZ_SUFFIX.sub('', s)
        parsed = parse_datetime(stripped) or parse_datetime(stripped.replace(' ', 'T'))
    if parsed is None:
        try:
            parsed = dt.datetime.fromisoformat(s[:19])
        except ValueError:
            return None
    if dj_timezone.is_naive(parsed):
        parsed = dj_timezone.make_aware(parsed)
    return parsed


class Command(BaseCommand):
    help = 'Import legacy Telegram Trade Tracker data (ledger.xlsx, states/, market.json…) into the database.'

    def add_arguments(self, parser):
        parser.add_argument('--dir', default=None,
                            help='Legacy tracker folder (default: settings.LEGACY_TRACKER_DIR)')

    @transaction.atomic
    def handle(self, *args, **opts):
        from django.conf import settings
        base = opts['dir'] or settings.LEGACY_TRACKER_DIR
        if not os.path.isdir(base):
            self.stderr.write(f'Not a directory: {base}')
            return

        stats = {'channels': 0, 'trades': 0, 'quotes': 0, 'qty_rules': 0, 'messages': 0,
                 'quotes_asof_unparsed': 0}

        # ---- channels from groups.json -------------------------------------
        name_by_short = {}
        gpath = os.path.join(base, 'groups.json')
        if os.path.exists(gpath):
            for g in json.load(open(gpath)):
                ch, _ = Channel.objects.update_or_create(
                    peer=str(g['peer']),
                    defaults={'name': g.get('name', ''), 'short': g.get('short', '')},
                )
                name_by_short[ch.short] = ch
                stats['channels'] += 1

        def channel_for(peer, name='', short=''):
            peer = str(peer)
            if Channel.objects.filter(peer=peer).exists():
                return Channel.objects.get(peer=peer)
            return Channel.objects.create(peer=peer, name=name or short or peer,
                                          short=short or (name or peer)[:24])

        # ---- trades from ledger.xlsx ---------------------------------------
        lpath = os.path.join(base, 'ledger.xlsx')
        if os.path.exists(lpath):
            import openpyxl
            wb = openpyxl.load_workbook(lpath, read_only=True)
            for sheet in wb.sheetnames:
                if sheet == 'Overview':
                    continue
                ws = wb[sheet]
                rows = list(ws.iter_rows(values_only=True))
                if len(rows) < 5:
                    continue
                title = str(rows[0][0] or '').replace(' — Trade Balance Sheet', '')
                peer = sheet
                src = str(rows[1][0] or '')
                if '#-100' in src:
                    peer = src.split('#')[1].split(' ')[0].split('·')[0].strip()
                ch = name_by_short.get(sheet) or channel_for(peer, name=title, short=sheet)
                for row in rows[4:]:
                    if not row or row[1] is None or row[0] is None:
                        continue  # blank / TOTAL footer rows
                    Trade.objects.update_or_create(
                        channel=ch, date=as_date(row[0]), trade=str(row[1]).strip(),
                        entry=as_float(row[3]), status=norm_status(row[10]),
                        defaults={
                            'direction': str(row[2] or ''),
                            'target': as_float(row[4]),
                            'stop_loss': as_float(row[5]),
                            'ltp_exit': as_float(row[6]),
                            'unrealized': as_float(row[7]),
                            'realized': as_float(row[8]),
                            'cumulative': as_float(row[9]),
                            'note': str(row[11] or ''),
                        },
                    )
                    stats['trades'] += 1
            wb.close()

        # ---- quantity rules -------------------------------------------------
        qpath = os.path.join(base, 'quantities.json')
        if os.path.exists(qpath):
            q = json.load(open(qpath))
            QuantityRule.objects.update_or_create(
                scope='default', key='', defaults={'qty': int(q.get('_default', 1))})
            stats['qty_rules'] += 1
            for sym, val in (q.get('by_symbol') or {}).items():
                QuantityRule.objects.update_or_create(
                    scope='symbol', key=sym, defaults={'qty': int(val)})
                stats['qty_rules'] += 1
            for peer, val in (q.get('by_group') or {}).items():
                QuantityRule.objects.update_or_create(
                    scope='group', key=str(peer), defaults={'qty': int(val)})
                stats['qty_rules'] += 1

        # ---- quotes from market.json ----------------------------------------
        mpath = os.path.join(base, 'market.json')
        if os.path.exists(mpath):
            m = json.load(open(mpath))
            for peer, syms in m.items():
                if peer.startswith('_') or not isinstance(syms, dict):
                    continue
                ch = channel_for(peer)
                for sym, info in syms.items():
                    if not isinstance(info, dict):
                        continue
                    raw_asof = info.get('asof')
                    asof = as_asof_datetime(raw_asof)
                    if raw_asof and asof is None:
                        stats['quotes_asof_unparsed'] += 1
                    Quote.objects.update_or_create(
                        channel=ch, symbol=sym,
                        defaults={'name': info.get('name', ''),
                                  'kind': info.get('kind', ''),
                                  'ltp': as_float(info.get('ltp')),
                                  'asof': asof},
                    )
                    stats['quotes'] += 1

        # ---- messages from states/*.json ------------------------------------
        for f in sorted(glob.glob(os.path.join(base, 'states', '*.json'))):
            try:
                d = json.load(open(f))
            except (json.JSONDecodeError, OSError):
                continue
            peer = d.get('peer') or os.path.basename(f)[:-5]
            if not str(peer).lstrip('-').isdigit():
                continue
            ch = channel_for(peer, name=d.get('name', ''))
            for mid, msg in (d.get('seen') or {}).items():
                ts = parse_datetime(str(msg.get('ts') or ''))
                TelegramMessage.objects.update_or_create(
                    channel=ch, mid=int(mid),
                    defaults={'text': msg.get('t') or msg.get('_text') or '',
                              'day_label': str(msg.get('d') or ''),
                              'ts': ts},
                )
                stats['messages'] += 1

        self.stdout.write(self.style.SUCCESS(
            'Imported: ' + ' · '.join(f"{k}={v}" for k, v in stats.items())))
