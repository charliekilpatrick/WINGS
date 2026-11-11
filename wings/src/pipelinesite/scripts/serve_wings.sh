#!/bin/bash
# Serve the pipelinesite demo behind gunicorn (nginx proxies to 127.0.0.1:8000).
set -euo pipefail
cd "$(dirname "$0")/.."
export PIPELINESITE_DEMO=1
export PIPELINESITE_SERVE=1
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-pipelinesite.settings_serve}"

HOST="${PIPELINESITE_GUNICORN_BIND:-127.0.0.1}"
PORT="${PIPELINESITE_PORT:-8000}"
WORKERS="${PIPELINESITE_GUNICORN_WORKERS:-3}"

PYTHON="${PYTHON:-python3.12}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python 3.12 is required (set PYTHON=... if it is not on PATH)." >&2
  exit 1
fi
if [ -d .venv ]; then
  VENV_MINOR="$(.venv/bin/python -c 'import sys; print("%s.%s" % sys.version_info[:2])' 2>/dev/null || true)"
  if [ "$VENV_MINOR" != "3.12" ]; then
    echo "Recreating .venv with Python 3.12 (was ${VENV_MINOR:-unknown})."
    rm -rf .venv
  fi
fi
if [ ! -d .venv ]; then
  "$PYTHON" -m venv .venv
fi
.venv/bin/pip install -q -r requirements-demo.txt

.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py setup_demo
.venv/bin/python manage.py collectstatic --noinput
if .venv/bin/python manage.py help ingest_campaign_index >/dev/null 2>&1; then
  .venv/bin/python manage.py ingest_campaign_index || true
fi

echo
echo "Gunicorn listening on ${HOST}:${PORT} (proxied by nginx on :80/:443)."
echo "SSH tunnel fallback: ssh -N -L ${PORT}:127.0.0.1:${PORT} ckilpatrick@burbidge.northwestern.edu"
echo

exec .venv/bin/gunicorn pipelinesite.wsgi:application \
  --bind "${HOST}:${PORT}" \
  --workers "${WORKERS}" \
  --timeout 120 \
  --access-logfile - \
  --error-logfile - \
  --capture-output
