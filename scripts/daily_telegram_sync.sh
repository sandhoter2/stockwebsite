#!/bin/bash
START=$(date +%s)
cd /Users/mamathap/Downloads/Telegram/telegram-trade-tracker
/usr/local/bin/python3 telethon_extract.py --limit 500 --no-build >> daily_telegram_sync.log 2>&1
EXIT1=$?
cd /Users/mamathap/Downloads/django
./.venv/bin/python manage.py import_legacy_data >> daily_telegram_sync.log 2>&1
EXIT2=$?
./.venv/bin/python manage.py parse_signals >> daily_telegram_sync.log 2>&1
EXIT3=$?
[ $EXIT1 -ne 0 -o $EXIT2 -ne 0 -o $EXIT3 -ne 0 ] && EXIT=1 || EXIT=0
./.venv/bin/python manage.py ktl_record telegram_sync "$START" "$EXIT" "extract=$EXIT1 import=$EXIT2 parse=$EXIT3" >> daily_telegram_sync.log 2>&1
