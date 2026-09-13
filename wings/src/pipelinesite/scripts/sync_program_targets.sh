#!/bin/bash
# Poll STScI visit status + MAST and add ready GO program targets to the campaign table.
set -euo pipefail
export PIPELINESITE_DEMO=1
cd "$(dirname "$0")/.."
exec .venv/bin/python manage.py sync_program_targets "$@"
