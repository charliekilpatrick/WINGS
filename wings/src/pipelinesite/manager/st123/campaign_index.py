"""Persist and read the campaign Program/Target/StageRun index."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import STAGES, find_target
from .host_distance import format_distance, lookup_host_distance
from .mast_updates import updates_by_target
from .programs import list_program_specs
from .status_tags import derive_status_tag, status_label_for_row


def _inventory():
    from . import inventory

    return inventory


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip().replace('Z', '')
        parsed = None
        for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M'):
            try:
                parsed = datetime.strptime(text[:19], fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def upsert_programs() -> int:
    from manager.models import Program

    n = 0
    for spec in list_program_specs():
        Program.objects.update_or_create(
            program_id=str(spec.program_id),
            defaults={
                'short_name': spec.short_name,
                'title': spec.title,
                'pi': spec.pi or '',
                'institution': spec.institution or '',
                'cycle': spec.cycle or '',
                'orbits': spec.orbits or '',
                'status': spec.status or '',
                'url': spec.url or '',
                'output_name': spec.output_name or '',
            },
        )
        n += 1
    return n


def _job_state_from_status(stored: dict[str, Any], *, new_data: bool, n_images: int, remaining: list[str]) -> str:
    inv = _inventory()
    state = stored.get('state') or 'idle'
    if state == 'running' and inv.pid_is_running(stored.get('pid')):
        return 'running'
    if new_data:
        return 'new'
    if not remaining:
        return 'completed' if n_images or state in {'completed', 'idle'} else 'pending'
    if state == 'error':
        return 'error'
    return 'pending'


def upsert_target_from_spec(spec, *, mast_flags: dict[str, dict[str, Any]] | None = None) -> Any:
    from manager.models import Program, StageRun, Target

    program, _ = Program.objects.get_or_create(
        program_id=str(spec.program_id),
        defaults={
            'short_name': f'GO {spec.program_id}',
            'title': f'GO {spec.program_id}',
        },
    )
    inv = _inventory()
    stored = inv.read_status_file(spec.base_dir)
    stored_stages = stored.get('stages') or {}
    flag = (mast_flags or {}).get(spec.name) or {}
    new_data = bool(flag.get('new_available'))
    n_new_obs = int(flag.get('n_pending') or 0)
    if 'n_images' in stored:
        n_images = int(stored.get('n_images') or 0)
    else:
        n_images = inv.count_science_fits(Path(spec.base_dir) / 'download')

    remaining: list[str] = []
    for stage in STAGES:
        record = stored_stages.get(stage.key) or {}
        state = record.get('state') or 'pending'
        if state not in {'completed', 'running', 'skipped'}:
            remaining.append(stage.key)

    job_state = _job_state_from_status(stored, new_data=new_data, n_images=n_images, remaining=remaining)
    status_tag = derive_status_tag(
        job_state=job_state,
        n_images=n_images,
        new_data=new_data,
        remaining=remaining,
    )
    distance = lookup_host_distance(
        host=spec.host,
        ra=spec.ra,
        dec=spec.dec,
        base_dir=spec.base_dir,
        remote=False,
    )
    instruments = ','.join(spec.instruments) if getattr(spec, 'instruments', None) else ''
    target, _ = Target.objects.update_or_create(
        name=spec.name,
        defaults={
            'program': program,
            'display_name': spec.display_name,
            'host': spec.host or '',
            'field_role': getattr(spec, 'field_role', 'prime') or 'prime',
            'sn_type': getattr(spec, 'sn_type', '') or '',
            'ra': float(spec.ra),
            'dec': float(spec.dec),
            'ra_sex': spec.ra_sex or '',
            'dec_sex': spec.dec_sex or '',
            'radius_arcmin': float(getattr(spec, 'radius_arcmin', 5.0) or 5.0),
            'instruments': instruments,
            'telescope': spec.telescope or 'hst',
            'base_dir': str(spec.base_dir),
            'notes': getattr(spec, 'notes', '') or '',
            'n_images': n_images,
            'job_state': job_state,
            'new_data': new_data,
            'n_new_obs': n_new_obs,
            'status_tag': status_tag,
            'distance_mpc': None if distance is None else distance.get('distance_mpc'),
            'distance_err_mpc': None if distance is None else distance.get('distance_err_mpc'),
            'distance_catalog': '' if distance is None else str(distance.get('catalog') or ''),
            'distance_display': format_distance(distance) or '',
            'redshift': None if distance is None else distance.get('redshift'),
            'has_catalog': bool(
                (stored_stages.get('run_dolphot') or {}).get('state') == 'completed'
                or inv.has_phot_files(spec.base_dir)
            ),
            'has_reference': bool(
                (stored_stages.get('mosaic') or {}).get('state') == 'completed'
                or inv.has_mosaic_coadd(spec.base_dir)
            ),
        },
    )
    for stage in STAGES:
        record = stored_stages.get(stage.key) or {}
        state = record.get('state') or 'pending'
        StageRun.objects.update_or_create(
            target=target,
            key=stage.key,
            defaults={
                'state': state,
                'started_at': _parse_dt(record.get('started_at')),
                'ended_at': _parse_dt(record.get('ended_at')),
                'seconds': None if record.get('seconds') is None else float(record.get('seconds')),
                'log': str(record.get('log') or ''),
            },
        )
    return target


def upsert_target_status(base_dir: Path, payload: dict[str, Any] | None = None) -> None:
    """Update ORM rows after write_status. Safe no-op if migrations are missing."""
    try:
        from manager.models import StageRun, Target
    except Exception:
        return
    try:
        target = Target.objects.filter(base_dir=str(base_dir)).first()
        if target is None:
            spec = find_target(Path(base_dir).name)
            if spec is None:
                return
            mast = updates_by_target(spec.program_id)
            upsert_target_from_spec(spec, mast_flags=mast)
            _inventory().clear_campaign_list_cache()
            return
        inv = _inventory()
        stored = payload if payload is not None else inv.read_status_file(base_dir)
        stored_stages = stored.get('stages') or {}
        n_images = int(stored.get('n_images') or target.n_images or 0)
        remaining = [
            stage.key
            for stage in STAGES
            if (stored_stages.get(stage.key) or {}).get('state') not in {'completed', 'running', 'skipped'}
        ]
        flag_new = bool(target.new_data)
        job_state = _job_state_from_status(
            stored, new_data=flag_new, n_images=n_images, remaining=remaining
        )
        target.n_images = n_images
        target.job_state = job_state
        target.status_tag = derive_status_tag(
            job_state=job_state,
            n_images=n_images,
            new_data=flag_new,
            remaining=remaining,
        )
        target.has_catalog = bool(
            (stored_stages.get('run_dolphot') or {}).get('state') == 'completed'
            or inv.has_phot_files(base_dir)
        )
        target.has_reference = bool(
            (stored_stages.get('mosaic') or {}).get('state') == 'completed'
            or inv.has_mosaic_coadd(base_dir)
        )
        target.save(
            update_fields=[
                'n_images',
                'job_state',
                'status_tag',
                'has_catalog',
                'has_reference',
                'updated_at',
            ]
        )
        for stage in STAGES:
            record = stored_stages.get(stage.key) or {}
            StageRun.objects.update_or_create(
                target=target,
                key=stage.key,
                defaults={
                    'state': record.get('state') or 'pending',
                    'started_at': _parse_dt(record.get('started_at')),
                    'ended_at': _parse_dt(record.get('ended_at')),
                    'seconds': None if record.get('seconds') is None else float(record.get('seconds')),
                    'log': str(record.get('log') or ''),
                },
            )
        inv.clear_campaign_list_cache()
    except Exception:
        return


def index_is_populated(program: str | None = None) -> bool:
    try:
        from manager.models import Target
    except Exception:
        return False
    try:
        qs = Target.objects.all()
        if program:
            qs = qs.filter(program__program_id=str(program))
        return qs.exists()
    except Exception:
        return False


def list_targets_from_db(program: str | None = None) -> list[dict[str, Any]] | None:
    """Return campaign list rows from the ORM, or None if the index is empty."""
    try:
        from manager.models import Target
    except Exception:
        return None
    try:
        qs = Target.objects.select_related('program').prefetch_related('stages')
        if program:
            qs = qs.filter(program__program_id=str(program))
        targets = list(qs)
        if not targets:
            return None
        inv = _inventory()
        rows: list[dict[str, Any]] = []
        for target in targets:
            by_key = {stage.key: stage for stage in target.stages.all()}
            stage_rows = []
            for spec in STAGES:
                stage = by_key.get(spec.key)
                state = stage.state if stage else 'pending'
                seconds = stage.seconds if stage else None
                stage_rows.append(
                    {
                        'key': spec.key,
                        'label': spec.label,
                        'cli': spec.cli,
                        'description': spec.description,
                        'state': state,
                        'started_at': None
                        if stage is None or stage.started_at is None
                        else stage.started_at.astimezone(timezone.utc).replace(tzinfo=None).strftime(
                            '%Y-%m-%dT%H:%M:%S'
                        ),
                        'ended_at': None
                        if stage is None or stage.ended_at is None
                        else stage.ended_at.astimezone(timezone.utc).replace(tzinfo=None).strftime(
                            '%Y-%m-%dT%H:%M:%S'
                        ),
                        'seconds': seconds,
                        'duration': None,
                        'log': stage.log if stage else None,
                    }
                )
            remaining = inv.remaining_stages(stage_rows)
            n_done = sum(1 for row in stage_rows if row['state'] in {'completed', 'skipped'})
            tag = target.status_tag or derive_status_tag(
                job_state=target.job_state,
                n_images=target.n_images,
                new_data=target.new_data,
                remaining=remaining,
                stages=stage_rows,
            )
            status = status_label_for_row(
                tag,
                n_images=target.n_images,
                n_new_obs=target.n_new_obs,
                remaining=remaining,
            )
            rows.append(
                {
                    'name': target.name,
                    'display_name': target.display_name,
                    'program_id': target.program.program_id,
                    'host': target.host,
                    'field_role': target.field_role,
                    'sn_type': target.sn_type,
                    'ra': target.ra,
                    'dec': target.dec,
                    'ra_sex': target.ra_sex,
                    'dec_sex': target.dec_sex,
                    'distance_display': target.distance_display,
                    'n_images': target.n_images,
                    'n_done': n_done,
                    'n_stages': len(STAGES),
                    'remaining': remaining,
                    'status': status,
                    'status_tag': tag,
                    'job_state': target.job_state,
                    'new_data': target.new_data,
                    'n_new_obs': target.n_new_obs,
                    'has_catalog': target.has_catalog,
                    'has_reference': target.has_reference,
                }
            )
        return rows
    except Exception:
        return None


def apply_mast_flags(program: str | None = None) -> int:
    """Push mast_updates.json flags into Target ORM rows. Returns updated count."""
    try:
        from manager.models import Target
    except Exception:
        return 0
    try:
        mast = updates_by_target(program)
        qs = Target.objects.select_related('program').prefetch_related('stages')
        if program:
            qs = qs.filter(program__program_id=str(program))
        updated = 0
        for target in qs:
            flag = mast.get(target.name) or {}
            new_data = bool(flag.get('new_available') or flag.get('new_data'))
            n_new_obs = int(flag.get('n_pending') or flag.get('n_new_obs') or 0)
            by_key = {stage.key: stage for stage in target.stages.all()}
            remaining = [
                stage.key
                for stage in STAGES
                if (by_key.get(stage.key).state if by_key.get(stage.key) else 'pending')
                not in {'completed', 'running', 'skipped'}
            ]
            job_state = target.job_state
            if new_data and job_state not in {'running', 'error'}:
                job_state = 'new'
            elif not new_data and job_state == 'new':
                job_state = 'completed' if not remaining else 'pending'
            tag = derive_status_tag(
                job_state=job_state,
                n_images=target.n_images,
                new_data=new_data,
                remaining=remaining,
            )
            if (
                target.new_data != new_data
                or target.n_new_obs != n_new_obs
                or target.job_state != job_state
                or target.status_tag != tag
            ):
                target.new_data = new_data
                target.n_new_obs = n_new_obs
                target.job_state = job_state
                target.status_tag = tag
                target.save(
                    update_fields=['new_data', 'n_new_obs', 'job_state', 'status_tag', 'updated_at']
                )
                updated += 1
        if updated:
            _inventory().clear_campaign_list_cache()
        return updated
    except Exception:
        return 0


def sync_science_products(target_name: str, inventory: dict[str, Any]) -> None:
    """Replace ScienceImage/Catalog rows for a target from page inventory payload."""
    import json

    try:
        from manager.models import Catalog, ScienceImage, Target
    except Exception:
        return
    try:
        target = Target.objects.filter(name=target_name).first()
        if target is None:
            return
        images = inventory.get('images') or []
        catalogs = inventory.get('catalogs') or []
        ScienceImage.objects.filter(target=target).delete()
        Catalog.objects.filter(target=target).delete()
        image_rows = []
        for row in images:
            image_rows.append(
                ScienceImage(
                    target=target,
                    filename=str(row.get('filename') or '')[:256],
                    relativepath=str(row.get('relativepath') or '')[:512],
                    telescope=str(row.get('telescope') or '')[:32],
                    instrument=str(row.get('instrument') or '')[:32],
                    filter=str(row.get('filter') or '')[:32],
                    exptime=None if row.get('exptime') in (None, '') else float(row.get('exptime')),
                    date_obs=str(row.get('date_obs') or '')[:32],
                    ra=None if row.get('ra') in (None, '') else float(row.get('ra')),
                    dec=None if row.get('dec') in (None, '') else float(row.get('dec')),
                    size_display=str(row.get('size_display') or '')[:64],
                    obsid=str(row.get('obsid') or '')[:64],
                    path=str(row.get('path') or '')[:1024],
                )
            )
        if image_rows:
            ScienceImage.objects.bulk_create(image_rows, batch_size=200)
        catalog_rows = []
        for row in catalogs:
            catalog_rows.append(
                Catalog(
                    target=target,
                    name=str(row.get('name') or '')[:256],
                    stem=str(row.get('stem') or row.get('name') or '')[:256],
                    path=str(row.get('path') or '')[:1024],
                    n_before=int(row.get('n_before') or 0),
                    n_after=int(row.get('n_after') or 0),
                    cuts_json=json.dumps(row.get('cuts') or {}),
                )
            )
        if catalog_rows:
            Catalog.objects.bulk_create(catalog_rows, batch_size=50)
        target.has_catalog = bool(catalog_rows)
        target.has_reference = bool(inventory.get('viewer_ready') or inventory.get('reference_image'))
        if images:
            target.n_images = len(images)
        target.save(update_fields=['has_catalog', 'has_reference', 'n_images', 'updated_at'])
    except Exception:
        return


def ingest_all(program: str | None = None) -> dict[str, int]:
    from .config import campaign_targets

    n_programs = upsert_programs()
    mast = updates_by_target(program)
    n_targets = 0
    for spec in campaign_targets(program):
        upsert_target_from_spec(spec, mast_flags=mast)
        n_targets += 1
    apply_mast_flags(program)
    _inventory().clear_campaign_list_cache()
    return {'programs': n_programs, 'targets': n_targets}
