#!/bin/bash
# Local development helper. Prefer scripts/serve_wings.sh (gunicorn) for the
# public burbidge site; see deploy/SUDO_CUTOVER.md.
set -euo pipefail
cd "$(dirname "$0")"
export PIPELINESITE_DEMO=1

HOST="${PIPELINESITE_BIND:-127.0.0.1}"
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
echo "Dev runserver on ${HOST}:${PORT}."
echo "Public site should use: scripts/serve_wings.sh (gunicorn) + nginx."
echo "SSH tunnel: ssh -N -L ${PORT}:127.0.0.1:${PORT} ckilpatrick@burbidge.northwestern.edu"
echo
exec .venv/bin/python manage.py runserver "${HOST}:${PORT}"
