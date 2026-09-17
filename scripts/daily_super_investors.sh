#!/bin/bash
cd /Users/mamathap/Downloads/django
./.venv/bin/python manage.py import_13f_filings >> daily_super_investors.log 2>&1
./.venv/bin/python manage.py update_current_prices >> daily_super_investors.log 2>&1
