#!/bin/bash
START=$(date +%s)
cd /Users/mamathap/Downloads/django
./.venv/bin/python manage.py import_13f_filings >> daily_super_investors.log 2>&1
EXIT1=$?
./.venv/bin/python manage.py update_current_prices >> daily_super_investors.log 2>&1
EXIT2=$?
[ $EXIT1 -ne 0 -o $EXIT2 -ne 0 ] && EXIT=1 || EXIT=0
./.venv/bin/python manage.py ktl_record super_investors "$START" "$EXIT" "13f=$EXIT1 prices=$EXIT2" >> daily_super_investors.log 2>&1
