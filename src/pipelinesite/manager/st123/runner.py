"""Dispatch and run st123 stages for the example target."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from .config import (
    STAGES,
    dispatch_lock_path,
    dolphot_bin_dir,
    find_target,
    ncores,
    st123_bin_dir,
    st123_root,
    status_dir,
    status_path,
    target_config,
)
from .inventory import (
    build_campaign_status,
    dispatch_availability,
    pid_is_running,
    read_status_file,
)


STAGE_BY_KEY = {spec.key: spec for spec in STAGES}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime('%Y-%m-%dT%H:%M:%S')


def write_status(base_dir: Path, payload: dict) -> None:
    path = status_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


def _stage_argv(stage_key: str, target) -> list[str]:
    spec = STAGE_BY_KEY[stage_key]
    binary = str(st123_bin_dir() / spec.cli)
    base = str(target.base_dir)
    cores = str(ncores())
    if stage_key == 'download':
        return [
            binary,
            '--telescope', target.telescope,
            '--ra', str(target.ra),
            '--dec', str(target.dec),
            '--radius', str(target.radius_arcmin),
            '--base-dir', base,
            '--instruments', *list(target.instruments),
            '-v',
        ]
    if stage_key == 'align':
        return [
            binary, '--base-dir', base,
            '--instruments', 'hst' if target.telescope == 'hst' else 'jwst',
            '--ncores', cores, '-v',
        ]
    if stage_key == 'mosaic':
        return [
            binary, '--base-dir', base,
            '--instruments', 'hst' if target.telescope == 'hst' else 'jwst',
            '--ncores', cores, '-v',
        ]
    if stage_key == 'prepare_dolphot':
        return [
            binary, '--base-dir', base,
            '--instruments', 'hst' if target.telescope == 'hst' else 'nircam',
            '--ncores', cores, '-v',
        ]
    if stage_key == 'run_dolphot':
        return [
            binary, '--base-dir', base,
            '--instruments', 'hst' if target.telescope == 'hst' else 'nircam',
            '--ncores', cores, '-v',
        ]
    if stage_key == 'combine_catalogs':
        return [
            binary,
            '--base-dir',
            base,
            '--instruments',
            'hst' if target.telescope == 'hst' else 'all',
            '-v',
        ]
    raise ValueError(f'Unknown stage {stage_key}')


def _env() -> dict[str, str]:
    env = os.environ.copy()
    bindir = str(st123_bin_dir())
    dolphot = str(dolphot_bin_dir())
    path_parts = [bindir, dolphot, env.get('PATH', '')]
    env['PATH'] = os.pathsep.join(p for p in path_parts if p)
    env['ST123_ROOT'] = str(st123_root())
    return env


@contextmanager
def _dispatch_lock():
    path = dispatch_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open('a+')
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def spawn_job(stage_keys: Sequence[str], target=None) -> dict:
    target = target or target_config()
    target.base_dir.mkdir(parents=True, exist_ok=True)
    if not stage_keys:
        raise RuntimeError('No stages requested')
    unknown = [key for key in stage_keys if key not in STAGE_BY_KEY]
    if unknown:
        raise RuntimeError(f'Unknown stages: {", ".join(unknown)}')

    with _dispatch_lock():
        gate = dispatch_availability(target)
        if not gate['allowed']:
            raise RuntimeError(gate['message'])
        status = read_status_file(target.base_dir)
        if status.get('state') == 'running' and pid_is_running(status.get('pid')):
            raise RuntimeError(f'A job is already running for {target.display_name}. Wait for it to finish.')

        manage = Path(__file__).resolve().parents[2] / 'manage.py'
        python = sys.executable
        cmd = [
            python,
            str(manage),
            'run_st123_job',
            '--target',
            target.name,
            '--stages',
            ','.join(stage_keys),
        ]
        status_dir(target.base_dir).mkdir(parents=True, exist_ok=True)
        log_path = status_dir(target.base_dir) / 'runner.log'
        handle = log_path.open('ab')
        env = os.environ.copy()
        env.setdefault('PIPELINESITE_DEMO', '1')
        proc = subprocess.Popen(
            cmd,
            cwd=str(manage.parent),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        payload = {
            'state': 'running',
            'pid': proc.pid,
            'started_at': _now_iso(),
            'ended_at': None,
            'message': f'Dispatched {", ".join(stage_keys)}',
            'requested_stages': list(stage_keys),
            'stages': status.get('stages') or {},
        }
        write_status(target.base_dir, payload)
        return payload


def run_stages(stage_keys: Iterable[str], target=None) -> None:
    from pipelinesite.utils import JobStates

    from .jobs import create_run_jobs, mark_job

    if target is None or isinstance(target, str):
        target = find_target(target) if target else target_config()
    if target is None:
        raise RuntimeError('Unknown target')
    target.base_dir.mkdir(parents=True, exist_ok=True)
    keys = [key for key in stage_keys if key in STAGE_BY_KEY]
    jobs = create_run_jobs(keys)
    job_by_stage = {}
    for key, job in zip(keys, jobs):
        job_by_stage[key] = job

    payload = read_status_file(target.base_dir)
    payload.update(
        {
            'state': 'running',
            'pid': os.getpid(),
            'started_at': payload.get('started_at') or _now_iso(),
            'ended_at': None,
            'message': f'Running {", ".join(keys)}',
            'requested_stages': keys,
            'stages': payload.get('stages') or {},
        }
    )
    write_status(target.base_dir, payload)

    env = _env()
    try:
        for key in keys:
            spec = STAGE_BY_KEY[key]
            job = job_by_stage.get(key)
            if job is not None:
                mark_job(job, JobStates.INITIALIZED.value[0], start=True)
            started = _now_iso()
            payload['stages'][key] = {
                'state': 'running',
                'started_at': started,
                'ended_at': None,
                'seconds': None,
                'log': None,
            }
            payload['message'] = f'Running {spec.label}'
            write_status(target.base_dir, payload)

            argv = _stage_argv(key, target)
            t0 = time.perf_counter()
            result = subprocess.run(
                argv,
                cwd=str(target.base_dir),
                env=env,
                check=False,
            )
            seconds = time.perf_counter() - t0
            ended = _now_iso()
            ok = result.returncode == 0
            payload['stages'][key] = {
                'state': 'completed' if ok else 'error',
                'started_at': started,
                'ended_at': ended,
                'seconds': seconds,
                'returncode': result.returncode,
                'command': argv,
            }
            write_status(target.base_dir, payload)
            if job is not None:
                mark_job(
                    job,
                    JobStates.COMPLETED.value[0] if ok else JobStates.ERROR.value[0],
                    end=True,
                )
            if not ok:
                raise RuntimeError(f'{spec.label} failed with exit {result.returncode}')
        payload['state'] = 'completed'
        payload['ended_at'] = _now_iso()
        payload['message'] = 'All requested stages finished'
        write_status(target.base_dir, payload)
    except Exception as exc:
        payload['state'] = 'error'
        payload['ended_at'] = _now_iso()
        payload['message'] = str(exc)
        write_status(target.base_dir, payload)
        raise


def campaign_context() -> dict:
    return build_campaign_status()
