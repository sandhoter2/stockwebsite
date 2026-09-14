#!/usr/bin/env bash
# Start (or restart) the Django server on :8000 and the ngrok public tunnel.
set -euo pipefail
cd "$(dirname "$0")"

# 1. Django server
if ! curl -s -o /dev/null http://127.0.0.1:8000/healthz/; then
  echo "→ starting Django on :8000"
  nohup ./.venv/bin/python manage.py runserver 0.0.0.0:8000 --noreload > runserver.log 2>&1 &
  sleep 2
fi

# 2. ngrok tunnel
if ! ngrok config check >/dev/null 2>&1; then
  echo "✗ ngrok not authenticated yet. Run:"
  echo "    ngrok config add-authtoken <YOUR_TOKEN>"
  echo "  Get a free token at https://dashboard.ngrok.com/get-started/your-authtoken"
  exit 1
fi
echo "→ opening ngrok tunnel to http://127.0.0.1:8000"
echo "  public URL appears below (and in ngrok.log); Ctrl-C stops the tunnel only."
ngrok http 8000 --log=ngrok.log --log-format=text
