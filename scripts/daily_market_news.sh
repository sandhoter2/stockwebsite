#!/bin/bash
# Alpha Vantage free tier is 25 requests/day -- this runs 6x/day (every 4h),
# well under that, since NEWS_SENTIMENT is one call per invocation regardless
# of --tickers/--topics filters.
START=$(date +%s)
cd /Users/mamathap/Downloads/django
set -a; source .env; set +a
./.venv/bin/python manage.py import_market_news >> daily_market_news.log 2>&1
EXIT=$?
./.venv/bin/python manage.py ktl_record market_news "$START" "$EXIT" "$(tail -1 daily_market_news.log)" >> daily_market_news.log 2>&1
