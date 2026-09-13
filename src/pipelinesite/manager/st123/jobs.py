"""Create and update Django wpipe-style job rows for an st123 run."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from django.utils import timezone as dj_timezone

from pipelinesite.models import (
    Configurations,
    Events,
    Jobs,
    Nodes,
    Optowners,
    Pipelines,
    Tasks,
)
from pipelinesite.utils import JobStates


def _now():
    return dj_timezone.now()


def _new_optowner(type_name: str):
    return Optowners.objects.create(timestamp=_now(), type=type_name)


def example_pipeline() -> Pipelines | None:
    return Pipelines.objects.filter(name='st123').first()


def example_config() -> Configurations | None:
    pipeline = example_pipeline()
    if pipeline is None:
        return None
    return Configurations.objects.filter(target__input__pipeline=pipeline).first()


def local_node() -> Nodes:
    node = Nodes.objects.filter(name='local-st123').first()
    if node is not None:
        return node
    return Nodes.objects.create(
        name='local-st123',
        timestamp=_now(),
        int_ip='127.0.0.1',
        ext_ip='127.0.0.1',
    )


def task_for(stage_key: str) -> Tasks | None:
    pipeline = example_pipeline()
    if pipeline is None:
        return None
    return Tasks.objects.filter(pipeline=pipeline, name=stage_key).first()


def create_run_jobs(stage_keys: Iterable[str]) -> list[Jobs]:
    config = example_config()
    node = local_node()
    parent = None
    created = []
    now = _now()
    for key in stage_keys:
        task = task_for(key)
        event = Events.objects.create(
            id=_new_optowner('event'),
            name=f'dispatch_{key}',
            tag='dispatch',
            jargs='{}',
            value=key,
            parent_job=parent,
        )
        job = Jobs.objects.create(
            id=_new_optowner('job'),
            attempt=1,
            state=JobStates.SUBMITTED.value[0],
            starttime=None,
            endtime=None,
            node=node,
            config=config,
            task=task,
            firing_event=event,
        )
        created.append(job)
        parent = job
    # Touch pipeline timestamp so the job list has a coherent run.
    if created:
        created[0].starttime = now
        created[0].save(update_fields=['starttime'])
    return created


def mark_job(job: Jobs, state: str, *, start: bool = False, end: bool = False) -> None:
    now = _now()
    job.state = state
    if start:
        job.starttime = now
    if end:
        job.endtime = now
    job.save()


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
