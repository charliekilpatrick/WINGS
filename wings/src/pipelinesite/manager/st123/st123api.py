"""Call st123 datamodel helpers from the demo site.

Prefer an in-process import. If that fails, run the same ``get_filter`` /
``get_instrument`` helpers through the st123 environment interpreter.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Sequence

from .config import st123_bin_dir, st123_root

_CACHE: dict[tuple[str, str, float], str | None] = {}

_HELPER = r'''
import json, sys
from st123.utils.helpers import get_filter, get_instrument

need = sys.argv[1]
out = {}
for path in sys.argv[2:]:
    try:
        value = get_filter(path) if need == "filter" else get_instrument(path)
    except Exception:
        value = None
    out[path] = value
print(json.dumps(out))
'''


def _st123_python() -> Path:
    bindir = st123_bin_dir()
    for name in ('python', 'python3.12', 'python3'):
        candidate = bindir / name
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


def _try_import_helpers():
    root = str(st123_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    from st123.utils.helpers import get_filter, get_instrument
    return get_filter, get_instrument


def _lookup_many(kind: str, paths: Sequence[Path]) -> dict[str, str | None]:
    files = [Path(path) for path in paths if path]
    if not files:
        return {}
    found: dict[str, str | None] = {}
    missing: list[Path] = []
    for path in files:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            found[str(path)] = None
            continue
        key = (kind, str(path), mtime)
        if key in _CACHE:
            found[str(path)] = _CACHE[key]
        else:
            missing.append(path)
    if not missing:
        return found
    values: dict[str, str | None] = {}
    try:
        get_filter, get_instrument = _try_import_helpers()
        helper = get_filter if kind == 'filter' else get_instrument
        for path in missing:
            try:
                values[str(path)] = helper(path)
            except Exception:
                values[str(path)] = None
    except Exception:
        cmd = [_st123_python(), '-c', _HELPER, kind, *[str(path) for path in missing]]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, 'ST123_ROOT': str(st123_root())},
        )
        if result.returncode != 0:
            values = {str(path): None for path in missing}
        else:
            try:
                values = json.loads(result.stdout)
            except json.JSONDecodeError:
                values = {str(path): None for path in missing}
    for path in missing:
        raw = values.get(str(path))
        text = None if raw in (None, '') else str(raw).strip()
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        _CACHE[(kind, str(path), mtime)] = text
        found[str(path)] = text
    return found


def filter_name(path: Path) -> str | None:
    """st123 ``get_filter``: lowercase science bandpass, or None."""
    return _lookup_many('filter', [Path(path)]).get(str(Path(path)))


def filter_names(paths: Iterable[Path]) -> dict[str, str | None]:
    return _lookup_many('filter', [Path(path) for path in paths])


def instrument_name(path: Path) -> str | None:
    """st123 ``get_instrument``: instrument name, or None."""
    return _lookup_many('instrument', [Path(path)]).get(str(Path(path)))


def display_filter(value: str | None) -> str | None:
    if not value:
        return None
    return str(value).strip().upper()
