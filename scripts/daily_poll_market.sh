#!/bin/bash
cd /Users/mamathap/Downloads/django
./.venv/bin/python manage.py poll_market >> daily_poll_market.log 2>&1
