#!/bin/bash
cd /Users/mamathap/Downloads/Telegram/telegram-trade-tracker
/usr/local/bin/python3 telethon_extract.py --limit 500 --no-build >> daily_telegram_sync.log 2>&1
cd /Users/mamathap/Downloads/django
./.venv/bin/python manage.py import_legacy_data >> daily_telegram_sync.log 2>&1
./.venv/bin/python manage.py parse_signals >> daily_telegram_sync.log 2>&1
