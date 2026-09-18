"""NSE trading-session guard, used by the live intraday sync cron so it can
run every 2 minutes around the clock and no-op instantly outside market
hours -- computing this in Python (IST is fixed, no DST) sidesteps having
to convert NSE hours into the host's local cron time twice a year.

ponytail: no NSE holiday calendar (Diwali, Republic Day, etc.) -- the guard
will say "open" on a trading holiday. Upgrade with a holiday list if a
holiday's false "open" actually causes a problem (worst case today: a few
wasted no-op Telegram/price fetches, not wrong data).
"""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
EOD_WINDOW_MINUTES = 3


def is_market_open(now=None):
    now = (now or datetime.now(IST)).astimezone(IST)
    if now.weekday() >= 5:  # Saturday, Sunday
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


def is_eod_window(now=None):
    """True in the last few minutes before market close -- the live-sync
    cron (every 2 min) uses this to trigger the same-day square-off
    without needing a separate cron schedule (and the IST-vs-host-DST
    arithmetic that would come with one)."""
    now = (now or datetime.now(IST)).astimezone(IST)
    if now.weekday() >= 5:
        return False
    close_dt = now.replace(hour=MARKET_CLOSE.hour, minute=MARKET_CLOSE.minute, second=0, microsecond=0)
    return timedelta(0) <= (close_dt - now) <= timedelta(minutes=EOD_WINDOW_MINUTES)


def ist_today(now=None):
    return (now or datetime.now(IST)).astimezone(IST).date()
