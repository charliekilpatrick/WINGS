#!/bin/bash
# Start a local example of the pipelinesite frontend with SQLite sample data.
set -euo pipefail
cd "$(dirname "$0")"
export PIPELINESITE_DEMO=1

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements-demo.txt
fi

.venv/bin/python manage.py migrate
.venv/bin/python manage.py setup_demo
echo
echo "Example site: http://127.0.0.1:8000/"
echo "Django admin: http://127.0.0.1:8000/admin/  (admin / admin)"
echo
exec .venv/bin/python manage.py runserver 127.0.0.1:8000
