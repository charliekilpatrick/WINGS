"""Compare MAST inventories to local downloads and flag new program data."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import TargetSpec, campaign_targets, find_target, mast_updates_path
from .program_sync import name_key, query_mast_observations
from .programs import list_program_specs
from .sky import separation_arcmin


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _norm_id(value: Any) -> str:
    return ''.join(ch for ch in str(value or '').upper() if ch.isalnum())


def local_image_tokens(base_dir: Path) -> set[str]:
    tokens: set[str] = set()
    root = Path(base_dir) / 'download'
    if not root.is_dir():
        return tokens
    for path in root.rglob('*.fits'):
        tokens.add(_norm_id(path.name))
        tokens.add(_norm_id(path.stem.split('_')[0]))
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            parts = path.parts
        for part in parts:
            token = _norm_id(part)
            if token:
                tokens.add(token)
    return tokens


def obs_on_disk(obs_id: str, tokens: Iterable[str]) -> bool:
    key = _norm_id(obs_id)
    if not key:
        return False
    have = {token for token in (_norm_id(item) for item in tokens) if token}
    if key in have:
        return True
    for n in (9, 8, 6):
        if len(key) < n:
            continue
        prefix = key[:n]
        if any(prefix in token or token.startswith(prefix) for token in have):
            return True
    return False


def assign_observations(
    targets: Iterable[TargetSpec],
    mast_rows: Iterable[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    specs = list(targets)
    assigned = {spec.name: [] for spec in specs}
    for row in mast_rows:
        try:
            ra = float(row['ra'])
            dec = float(row['dec'])
        except (KeyError, TypeError, ValueError):
            ra = dec = None
        best = None
        best_sep = None
        if ra is not None and dec is not None:
            for spec in specs:
                try:
                    sep = separation_arcmin(ra, dec, spec.ra, spec.dec)
                except (TypeError, ValueError):
                    continue
                radius = float(spec.radius_arcmin or 5.0)
                if sep <= radius and (best_sep is None or sep < best_sep):
                    best = spec
                    best_sep = sep
        if best is None:
            keys = {name_key(row.get('target_name')), name_key(row.get('key'))}
            keys.discard('')
            hits = [
                spec
                for spec in specs
                if name_key(spec.name) in keys
                or name_key(spec.display_name) in keys
                or name_key(spec.host) in keys
            ]
            if hits:
                hits.sort(key=lambda spec: 0 if spec.field_role != 'parallel' else 1)
                best = hits[0]
        if best is not None:
            assigned[best.name].append(row)
    return assigned


def load_updates(program: str, *, refresh_local: bool = True) -> dict[str, Any]:
    path = mast_updates_path(program)
    if not path.is_file():
        return {
            'program_id': str(program),
            'checked_at': '',
            'n_new_targets': 0,
            'targets': [],
        }
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        data = {}
    data.setdefault('program_id', str(program))
    data.setdefault('targets', [])
    if refresh_local:
        _refresh_local_pending(data)
    data['n_new_targets'] = sum(1 for row in data.get('targets') or [] if row.get('new_available'))
    return data


def updates_by_target(program: str | None = None) -> dict[str, dict[str, Any]]:
    programs = [program] if program else [spec.program_id for spec in list_program_specs()]
    out: dict[str, dict[str, Any]] = {}
    for pid in programs:
        for row in load_updates(str(pid)).get('targets') or []:
            name = row.get('name')
            if name:
                out[str(name)] = row
    return out


def _refresh_local_pending(data: dict[str, Any]) -> None:
    for row in data.get('targets') or []:
        spec = find_target(row.get('name') or '')
        pending = [obs for obs in row.get('pending_obs_ids') or [] if obs]
        if spec is not None:
            tokens = local_image_tokens(spec.base_dir)
            pending = [obs for obs in pending if not obs_on_disk(obs, tokens)]
        row['pending_obs_ids'] = pending
        row['n_pending'] = len(pending)
        row['new_available'] = bool(pending)


def write_updates(program: str, payload: dict[str, Any]) -> Path:
    dest = mast_updates_path(program)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(dest)
    return dest


def check_program_updates(
    program: str,
    *,
    mast_rows: list[dict[str, Any]] | None = None,
    targets: list[TargetSpec] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    pid = str(program)
    specs = list(targets if targets is not None else campaign_targets(pid))
    mast = mast_rows if mast_rows is not None else query_mast_observations(pid)
    assigned = assign_observations(specs, mast)
    previous = load_updates(pid, refresh_local=False)
    prev_rows = {row.get('name'): row for row in previous.get('targets') or []}
    first_seen = not any(prev_rows.values())

    rows = []
    for spec in specs:
        current = {
            _norm_id(row.get('obs_id'))
            for row in assigned.get(spec.name) or []
            if _norm_id(row.get('obs_id'))
        }
        prior = prev_rows.get(spec.name) or {}
        seen = {_norm_id(item) for item in prior.get('seen_obs_ids') or [] if _norm_id(item)}
        pending = {_norm_id(item) for item in prior.get('pending_obs_ids') or [] if _norm_id(item)}
        if seen and not first_seen:
            pending |= current - seen
        tokens = local_image_tokens(spec.base_dir)
        pending = {obs for obs in pending if obs in current and not obs_on_disk(obs, tokens)}
        seen |= current
        rows.append(
            {
                'name': spec.name,
                'display_name': spec.display_name,
                'n_mast': len(current),
                'n_pending': len(pending),
                'new_available': bool(pending),
                'pending_obs_ids': sorted(pending),
                'seen_obs_ids': sorted(seen),
            }
        )
    payload = {
        'program_id': pid,
        'checked_at': _now_iso(),
        'n_mast': len(mast),
        'n_targets': len(rows),
        'n_new_targets': sum(1 for row in rows if row['new_available']),
        'targets': rows,
    }
    if not dry_run:
        payload['registry'] = str(write_updates(pid, payload))
        from .inventory import revert_status_for_new_data

        for spec, row in zip(specs, rows):
            if row.get('new_available'):
                revert_status_for_new_data(spec.base_dir)
    return payload


def check_all_programs(*, dry_run: bool = False) -> list[dict[str, Any]]:
    return [
        check_program_updates(spec.program_id, dry_run=dry_run)
        for spec in list_program_specs()
    ]
