#!/bin/bash
START=$(date +%s)
cd /Users/mamathap/Downloads/django
./.venv/bin/python manage.py poll_market >> daily_poll_market.log 2>&1
EXIT=$?
./.venv/bin/python manage.py ktl_record poll_market "$START" "$EXIT" "$(tail -2 daily_poll_market.log | tr '\n' ' ')" >> daily_poll_market.log 2>&1
