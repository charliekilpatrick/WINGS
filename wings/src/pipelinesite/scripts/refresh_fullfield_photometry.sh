#!/usr/bin/env bash
# Re-plan HST mosaic stamps with multi-SCI footprints (full ACS/WFC) and
# re-run DOLPHOT + HDF5 for campaign targets. Safe to nohup overnight.
#
# Usage:
#   ./refresh_fullfield_photometry.sh --dry-run
#   ./refresh_fullfield_photometry.sh --limit 1 --target ngc1255
#   nohup ./refresh_fullfield_photometry.sh >>logs/fullfield_refresh.log 2>&1 &
#
set -uo pipefail

PIPELINESITE="${PIPELINESITE:-/data/ckilpatrick/WINGS/wings/src/pipelinesite}"
ST123_ENV="${ST123_ENV:-/home/ckilpatrick/anaconda3/envs/st123}"
MARKER_NAME="fullfield_refresh_v1"
STAGES_DEFAULT="mosaic,prepare_dolphot,run_dolphot,combine_catalogs"

DRY_RUN=0
LIMIT=0
NO_CLEAR=0
FORCE=0
PROGRAMS=()
TARGETS=()
STAGES="$STAGES_DEFAULT"
LOG_ROOT="${LOG_ROOT:-$PIPELINESITE/logs}"

usage() {
  sed -n '1,20p' "$0"
  cat <<EOF

Options:
  --dry-run          List targets only
  --limit N          Process at most N targets
  --target NAME      Restrict to one target (repeatable)
  --program ID       Restrict to program id (repeatable; e.g. 18338)
  --stages LIST      Comma-separated stages (default: $STAGES_DEFAULT)
  --no-clear         Do not delete old group_*/dolphot stamps (not recommended)
  --force            Re-run even if marker $MARKER_NAME exists
  --log-root DIR     Summary / nohup-friendly log directory (default: $LOG_ROOT)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --limit) LIMIT="${2:?}"; shift 2 ;;
    --target) TARGETS+=("$2"); shift 2 ;;
    --program) PROGRAMS+=("$2"); shift 2 ;;
    --stages) STAGES="$2"; shift 2 ;;
    --no-clear) NO_CLEAR=1; shift ;;
    --force) FORCE=1; shift ;;
    --log-root) LOG_ROOT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

mkdir -p "$LOG_ROOT"
SUMMARY="$LOG_ROOT/fullfield_refresh_summary_$(date +%Y%m%d_%H%M%S).tsv"
exec > >(tee -a "$LOG_ROOT/fullfield_refresh_nohup.log") 2>&1

echo "==== fullfield refresh $(date -Is) ===="
echo "PIPELINESITE=$PIPELINESITE"
echo "ST123_ENV=$ST123_ENV"
echo "STAGES=$STAGES dry_run=$DRY_RUN limit=$LIMIT force=$FORCE no_clear=$NO_CLEAR"
echo "summary -> $SUMMARY"

if [[ ! -x "$ST123_ENV/bin/mosaic" ]]; then
  echo "ERROR: mosaic not found in $ST123_ENV/bin" >&2
  exit 1
fi
if [[ ! -x "$PIPELINESITE/.venv/bin/python" ]]; then
  echo "ERROR: pipelinesite venv missing at $PIPELINESITE/.venv" >&2
  exit 1
fi

# Prefer st123 CLI binaries for mosaic/dolphot.
export PATH="$ST123_ENV/bin:/data/software/dolphot/bin:$PATH"
export ST123_ROOT="${ST123_ROOT:-/data/ckilpatrick/st123}"
export PIPELINESITE_DEMO=1
export PIPELINESITE_SERVE=1
export DJANGO_SETTINGS_MODULE=pipelinesite.settings_serve

# Serialize against the WINGS web dispatcher.
LOCK="$PIPELINESITE/.pipelinesite_dispatch.lock"
mkdir -p "$(dirname "$LOCK")"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "ERROR: another WINGS/st123 job holds $LOCK; stop it or wait." >&2
  exit 1
fi

# Pass filters via env for the embedded python
export REFRESH_PROGRAMS="$(IFS=,; echo "${PROGRAMS[*]-}")"
export REFRESH_TARGETS="$(IFS=,; echo "${TARGETS[*]-}")"
mapfile -t TARGET_LINES < <(
  cd "$PIPELINESITE" && REFRESH_PROGRAMS="$REFRESH_PROGRAMS" REFRESH_TARGETS="$REFRESH_TARGETS" \
  .venv/bin/python - <<'PY'
import os
os.environ.setdefault('PIPELINESITE_DEMO', '1')
os.environ.setdefault('PIPELINESITE_SERVE', '1')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pipelinesite.settings_serve')
import django
django.setup()
from pathlib import Path
from manager.st123.config import campaign_targets

programs = [p for p in os.environ.get('REFRESH_PROGRAMS', '').split(',') if p]
wanted = {t for t in os.environ.get('REFRESH_TARGETS', '').split(',') if t}
for spec in campaign_targets():
    if programs and str(spec.program_id) not in programs:
        continue
    if wanted and spec.name not in wanted:
        continue
    red = Path(spec.base_dir) / 'reduction'
    jhat = list(red.rglob('*_jhat.fits')) if red.is_dir() else []
    if not jhat:
        continue
    print(f'{spec.name}\t{spec.program_id}\t{spec.base_dir}\t{len(jhat)}')
PY
)

n=${#TARGET_LINES[@]}
echo "Eligible targets with JHAT frames: $n"
if [[ "$LIMIT" -gt 0 && "$n" -gt "$LIMIT" ]]; then
  TARGET_LINES=("${TARGET_LINES[@]:0:$LIMIT}")
  echo "Limited to ${#TARGET_LINES[@]} target(s)"
fi

printf 'name\tprogram\tbase_dir\tn_jhat\tstatus\tnote\n' >"$SUMMARY"

ok=0
fail=0
skip=0
i=0
for line in "${TARGET_LINES[@]}"; do
  IFS=$'\t' read -r name program base n_jhat <<<"$line"
  i=$((i + 1))
  marker="$base/.pipelinesite/$MARKER_NAME"
  echo
  echo "---- [$i/${#TARGET_LINES[@]}] $name (GO $program, ${n_jhat} jhat) ----"
  if [[ "$FORCE" -eq 0 && -f "$marker" ]]; then
    echo "SKIP already refreshed ($marker)"
    printf '%s\t%s\t%s\t%s\tskipped\talready_done\n' "$name" "$program" "$base" "$n_jhat" >>"$SUMMARY"
    skip=$((skip + 1))
    continue
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "DRY-RUN would clear stamps and run: $STAGES"
    printf '%s\t%s\t%s\t%s\tdry-run\tok\n' "$name" "$program" "$base" "$n_jhat" >>"$SUMMARY"
    ok=$((ok + 1))
    continue
  fi

  if [[ "$NO_CLEAR" -eq 0 ]]; then
    # Drop boxed stamps so mosaic re-plans with multi-SCI footprints.
    rm -rf "$base/reduction/reference"/group_*
    rm -rf "$base/dolphot"/hst_*
    rm -f "$base/.pipelinesite"/preview_* \
          "$base/.pipelinesite"/page_inventory.json \
          "$base/.pipelinesite"/sources_*.json
    mkdir -p "$base/reduction/reference" "$base/dolphot" "$base/.pipelinesite"
  fi

  if ! (
    cd "$PIPELINESITE" && \
    .venv/bin/python manage.py run_st123_job --target "$name" --stages "$STAGES"
  ); then
    echo "FAIL $name"
    printf '%s\t%s\t%s\t%s\tfail\trun_st123_job\n' "$name" "$program" "$base" "$n_jhat" >>"$SUMMARY"
    fail=$((fail + 1))
    continue
  fi

  mkdir -p "$base/.pipelinesite"
  date -Is >"$marker"
  echo "OK $name"
  printf '%s\t%s\t%s\t%s\tok\t\n' "$name" "$program" "$base" "$n_jhat" >>"$SUMMARY"
  ok=$((ok + 1))
done

echo
echo "==== done $(date -Is) ok=$ok fail=$fail skip=$skip ===="
echo "Summary: $SUMMARY"
exit $([[ "$fail" -eq 0 ]] && echo 0 || echo 1)
