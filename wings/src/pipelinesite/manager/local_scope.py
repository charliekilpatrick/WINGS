"""Limit list views to pipelines that live on this machine."""

from __future__ import annotations

from pipelinesite.models import Events, Jobs, Pipelines, Tasks

_LOCAL_PREFIXES = ('/data/ckilpatrick', '/home/ckilpatrick')
_SKIP_MARKERS = ('/tmp/', 'wings-demo', 'example_photometry')


def is_local_pipeline(pipeline) -> bool:
    if pipeline is None:
        return False
    if pipeline.name == 'st123':
        return True
    blobs = ' '.join(
        str(getattr(pipeline, field, '') or '')
        for field in ('pipe_root', 'software_root', 'data_root', 'input_root', 'name')
    )
    if any(marker in blobs for marker in _SKIP_MARKERS):
        return False
    return any(blobs.startswith(prefix) or f' {prefix}' in f' {blobs}' for prefix in _LOCAL_PREFIXES)


def local_pipelines():
    keep_ids = [pipe.pk for pipe in Pipelines.objects.all() if is_local_pipeline(pipe)]
    return Pipelines.objects.filter(pk__in=keep_ids)


def local_tasks():
    return Tasks.objects.filter(pipeline__in=local_pipelines())


def local_jobs():
    return Jobs.objects.filter(task__in=local_tasks())


def local_events():
    jobs = local_jobs()
    return Events.objects.filter(parent_job__in=jobs) | Events.objects.filter(
        id__in=jobs.values_list('firing_event_id', flat=True)
    )
