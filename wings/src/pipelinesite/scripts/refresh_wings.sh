#!/bin/bash
# Reload WINGS pipelinesite gunicorn so code/static changes go live.
# Prefer systemd when passwordless sudo works; otherwise restart as this user.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
export PIPELINESITE_DEMO=1
export PIPELINESITE_SERVE=1
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-pipelinesite.settings_serve}"
export PIPELINESITE_GUNICORN_BIND="${PIPELINESITE_GUNICORN_BIND:-127.0.0.1}"
export PIPELINESITE_PORT="${PIPELINESITE_PORT:-8000}"
export PIPELINESITE_GUNICORN_WORKERS="${PIPELINESITE_GUNICORN_WORKERS:-3}"

if sudo -n systemctl restart wings-pipelinesite.service 2>/dev/null; then
  sleep 2
  if curl -sf -o /dev/null "http://127.0.0.1:${PIPELINESITE_PORT}/"; then
    echo "Restarted wings-pipelinesite.service"
    exit 0
  fi
fi

# Stop whatever is bound to the serve port (systemd unit or a prior manual start).
if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PIPELINESITE_PORT}/tcp" 2>/dev/null || true
fi
pkill -f 'gunicorn pipelinesite.wsgi:application' 2>/dev/null || true
sleep 1

# Skip the heavy serve_wings.sh bootstrap; just reload workers with current tree.
mkdir -p /tmp
nohup "$ROOT/.venv/bin/gunicorn" pipelinesite.wsgi:application \
  --bind "${PIPELINESITE_GUNICORN_BIND}:${PIPELINESITE_PORT}" \
  --workers "${PIPELINESITE_GUNICORN_WORKERS}" \
  --timeout 120 \
  --access-logfile /tmp/wings-access.log \
  --error-logfile /tmp/wings-error.log \
  --capture-output \
  --pid /tmp/wings-gunicorn.pid \
  >/tmp/wings-pipelinesite.log 2>&1 &

for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -sf -o /dev/null "http://127.0.0.1:${PIPELINESITE_PORT}/"; then
    echo "Gunicorn listening on ${PIPELINESITE_GUNICORN_BIND}:${PIPELINESITE_PORT}"
    exit 0
  fi
  sleep 1
done

echo "Failed to refresh pipelinesite; see /tmp/wings-error.log" >&2
tail -n 40 /tmp/wings-error.log >&2 || true
exit 1
