#!/bin/bash
# Start a local example of the pipelinesite frontend with SQLite sample data.
# Bind on all interfaces so a laptop can reach the site via SSH tunnel
# (recommended) or, on the campus network, http://burbidge.northwestern.edu:8000/.
set -euo pipefail
cd "$(dirname "$0")"
export PIPELINESITE_DEMO=1

HOST="${PIPELINESITE_BIND:-0.0.0.0}"
PORT="${PIPELINESITE_PORT:-8000}"

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

.venv/bin/python manage.py migrate
.venv/bin/python manage.py setup_demo
echo
echo "On burbidge:     http://127.0.0.1:${PORT}/"
echo "Campus / VPN:    http://burbidge.northwestern.edu:${PORT}/"
echo "Target page:     http://burbidge.northwestern.edu:${PORT}/manager/targets/2026dix"
echo
echo "From a remote laptop (works off-campus), keep this SSH tunnel open:"
echo "  ssh -N -L ${PORT}:127.0.0.1:${PORT} ckilpatrick@burbidge.northwestern.edu"
echo "  then open http://127.0.0.1:${PORT}/"
echo
exec .venv/bin/python manage.py runserver "${HOST}:${PORT}"
