"""Derive triage tags for campaign targets."""

from __future__ import annotations

from typing import Any


TAG_LABELS = {
    'running': 'Running',
    'new_data': 'New MAST data',
    'empty_mast': 'Empty MAST (0/0)',
    'unusable': 'No data',
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
    unusable: bool = False,
) -> str:
    state = (job_state or 'pending').lower()
    if state == 'running' or (stages and any(row.get('state') == 'running' for row in stages)):
        return 'running'
    if new_data or state == 'new':
        return 'new_data'
    if state == 'error':
        return 'error'
    remaining = remaining or []
    n_images = int(n_images or 0)
    download_row = next((row for row in (stages or []) if row.get('key') == 'download'), None)
    if unusable or (
        state in {'completed', 'idle'} and download_row and download_row.get('unusable')
    ):
        return 'unusable'
    # Job finished with zero science frames: treat as empty MAST even when later
    # stages were left pending (download-only re-run before skip-rest fix).
    if (
        n_images == 0
        and state in {'completed', 'idle'}
        and download_row
        and download_row.get('state') == 'completed'
    ):
        return 'empty_mast'
    if not remaining and n_images == 0:
        return 'empty_mast'
    if not remaining or state == 'completed':
        return 'complete' if n_images > 0 else 'empty_mast'
    return 'pending'


def status_label_for_row(tag: str, *, n_images: int = 0, n_new_obs: int = 0, remaining: list[str] | None = None) -> str:
    remaining = remaining or []
    if tag == 'running':
        return 'running'
    if tag == 'new_data':
        return f'new data available ({n_new_obs})' if n_new_obs else 'new data available'
    if tag == 'empty_mast':
        return 'no data yet (0/0)'
    if tag == 'unusable':
        return 'no data'
    if tag == 'complete':
        return 'complete'
    if tag == 'error':
        return 'error'
    if remaining:
        return f'{remaining[0]} pending'
    return 'pending'
