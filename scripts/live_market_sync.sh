#!/bin/bash
# Runs every 2 minutes via cron, all day -- guarded entirely in Python
# (traderacker.market_hours), never by crontab clock time. That's not a
# style preference: this box runs in US Central, the channels post on
# Indian market hours, and a naive `0 7 * * *`-style fixed-clock cron line
# is 7am in the HOST's timezone, not IST -- it drifts against IST-vs-host
# DST twice a year, and on this host currently lands at 5:30pm IST for a
# job meant to run pre-market. Computing the window in Python each tick
# sidesteps that entirely, and ticking every 2 min means the arithmetic
# never depends on the host clock's own timezone at all.
#
# mkdir-lock guards against overlap: if a run is still going (e.g. a slow
# Telegram fetch) when the next tick fires, that tick skips rather than
# stacking a second concurrent pass on the same sqlite db. (mkdir, not
# flock -- this host is macOS, which doesn't ship flock; mkdir is atomic
# on any POSIX filesystem so it works just as well as a lock primitive.)
cd /Users/mamathap/Downloads/django || exit 1
LOCKDIR=/tmp/live_market_sync.lock.d
mkdir "$LOCKDIR" 2>/dev/null || exit 0
trap 'rmdir "$LOCKDIR"' EXIT

./.venv/bin/python manage.py premarket_status > /dev/null 2>&1
PREMARKET=$?
if [ $PREMARKET -ne 0 ]; then
  ./.venv/bin/python manage.py market_status > /dev/null 2>&1 || exit 0
fi

START=$(date +%s)
cd /Users/mamathap/Downloads/Telegram/telegram-trade-tracker || exit 1
# Small --limit normally: this runs every 2 min, so only the last couple
# of minutes' messages are new -- the per-(channel,mid) unique constraint
# makes re-fetching the same recent window harmless, just wasted work at
# --limit 500. Bigger limit once a day in the pre-market window (~7am
# IST, market itself still closed) to catch the full overnight backlog --
# this replaces the old daily_telegram_sync.sh cron, which had the exact
# host-timezone-vs-IST bug described above.
EXTRACT_LIMIT=30
[ $PREMARKET -eq 0 ] && EXTRACT_LIMIT=500
/usr/local/bin/python3 telethon_extract.py --limit $EXTRACT_LIMIT --no-build >> live_market_sync.log 2>&1
EXIT1=$?
cd /Users/mamathap/Downloads/django || exit 1
./.venv/bin/python manage.py import_legacy_data >> live_market_sync.log 2>&1
EXIT2=$?
./.venv/bin/python manage.py parse_signals >> live_market_sync.log 2>&1
EXIT3=$?
# Opens a PaperTrade for each user's auto_consumers' new Open signals --
# was written months ago but never scheduled anywhere, so selecting
# channels in the Paper Trading picker and saving never actually did
# anything. Runs right after parse_signals, per its own docstring.
./.venv/bin/python manage.py paper_autotrade >> live_market_sync.log 2>&1
EXIT4=$?
./.venv/bin/python manage.py poll_market >> live_market_sync.log 2>&1
EXIT5=$?
[ $EXIT1 -ne 0 -o $EXIT2 -ne 0 -o $EXIT3 -ne 0 -o $EXIT4 -ne 0 -o $EXIT5 -ne 0 ] && EXIT=1 || EXIT=0
./.venv/bin/python manage.py ktl_record live_market_sync "$START" "$EXIT" \
  "extract=$EXIT1 import=$EXIT2 parse=$EXIT3 autotrade=$EXIT4 poll=$EXIT5" >> live_market_sync.log 2>&1
