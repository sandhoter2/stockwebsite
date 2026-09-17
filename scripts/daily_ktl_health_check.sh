#!/bin/bash
cd /Users/mamathap/Downloads/django
./.venv/bin/python manage.py ktl_health_check >> daily_ktl_health_check.log 2>&1
