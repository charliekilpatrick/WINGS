"""Derive triage tags for campaign targets."""

from __future__ import annotations

from typing import Any


TAG_LABELS = {
    'running': 'Running',
    'new_data': 'New MAST data',
    'empty_mast': 'Empty MAST (0/0)',
    'complete': 'Complete',
    'error': 'Error',
    'pending': 'Pending',
}


def derive_status_tag(
    *,
    job_state: str,
    n_images: int,
    new_data: bool,
    remaining: list[str] | None = None,
    stages: list[dict[str, Any]] | None = None,
) -> str:
    state = (job_state or 'pending').lower()
    if state == 'running' or (stages and any(row.get('state') == 'running' for row in stages)):
        return 'running'
    if new_data or state == 'new':
        return 'new_data'
    if state == 'error':
        return 'error'
    remaining = remaining or []
    if not remaining and int(n_images or 0) == 0:
        return 'empty_mast'
    if not remaining or state == 'completed':
        return 'complete' if int(n_images or 0) > 0 else 'empty_mast'
    return 'pending'


def status_label_for_row(tag: str, *, n_images: int = 0, n_new_obs: int = 0, remaining: list[str] | None = None) -> str:
    remaining = remaining or []
    if tag == 'running':
        return 'running'
    if tag == 'new_data':
        return f'new data available ({n_new_obs})' if n_new_obs else 'new data available'
    if tag == 'empty_mast':
        return 'no data yet (0/0)'
    if tag == 'complete':
        return 'complete'
    if tag == 'error':
        return 'error'
    if remaining:
        return f'{remaining[0]} pending'
    return 'pending'
