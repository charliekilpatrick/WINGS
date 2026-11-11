from __future__ import annotations

from urllib.parse import urlencode

from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from pathlib import Path

from manager.st123.config import find_target, target_config
from manager.st123.programs import find_program
from manager.st123.gaia import format_wcs_quality, load_gaia_overlay
from manager.st123.hdf5_export import ensure_catalog_hdf5
from manager.st123.inventory import (
    build_campaign_status,
    build_page_inventory,
    discover_phot_files,
    discover_reference_for_phot,
    discover_reference_image,
    dispatch_availability,
    list_campaign_targets,
    ensure_sources_overlay,
    resolve_display_image,
    source_photometry,
    warm_mosaic_previews,
    warm_page_inventory,
)
from manager.st123.config import mosaic_preview_static_base_url
from manager.st123.preview import build_preview, choose_preview_file
from manager.st123.runner import spawn_job
from manager.st123.sky import read_image_header


def _status(target=None, *, heavy=False):
    spec = target or target_config()
    return build_campaign_status(spec.base_dir, target=spec, heavy=heavy)


def _spec_or_404(name):
    if not name:
        return target_config()
    spec = find_target(name)
    if spec is None:
        raise Http404(f'Unknown target {name}')
    spec.base_dir.mkdir(parents=True, exist_ok=True)
    return spec


def _attach_wcs_quality(status, spec):
    if not status.get('viewer_ready') and not status.get('reference_image'):
        status['wcs_quality'] = ''
        return status
    meta = build_preview(spec.base_dir)
    gaia = load_gaia_overlay(spec.base_dir, (meta or {}).get('wcs'))
    status['wcs_quality'] = format_wcs_quality(gaia)
    return status


def campaign_home(request):
    return redirect('program_campaign', program_id='18338')


def target_search(request):
    query = request.GET.get('q', '')
    return redirect(reverse('home_page') + '?' + urlencode({'q': query}))


def target_detail(request, name):
    spec = _spec_or_404(name)
    status = _status(spec, heavy=False)
    if not status.get('inventory_ready'):
        warm_page_inventory(spec.base_dir)
    if status.get('viewer_ready') or status.get('reference_image') or status.get('mosaics'):
        warm_mosaic_previews(spec.base_dir)
    status['preview_static_base'] = mosaic_preview_static_base_url(spec.base_dir)
    return render(
        request,
        'campaign/target.html',
        {
            'campaign': status,
            'program': find_program(spec.program_id),
        },
    )


@require_GET
def campaign_status(request, name=None):
    spec = _spec_or_404(name or request.GET.get('target'))
    return JsonResponse(_status(spec, heavy=False))


@require_GET
def target_inventory(request, name):
    spec = _spec_or_404(name)
    return JsonResponse(build_page_inventory(spec.base_dir))


@require_POST
def campaign_dispatch(request, name=None):
    spec = _spec_or_404(name or request.POST.get('target') or request.GET.get('target'))
    status = _status(spec)
    rerun_all = request.POST.get('rerun_all') in {'1', 'true', 'on', 'yes'}
    raw = request.POST.get('stages', '').strip()
    if raw:
        stages = [part.strip() for part in raw.split(',') if part.strip()]
    elif rerun_all or status.get('new_data'):
        stages = [row['key'] for row in status['stages']]
    else:
        stages = status['remaining'] or [row['key'] for row in status['stages']]
    try:
        payload = spawn_job(stages, target=spec)
    except Exception as exc:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'ok': False, 'error': str(exc)}, status=409)
        return render(
            request,
            'campaign/target.html',
            {
                'campaign': _attach_wcs_quality(_status(spec), spec),
                'program': find_program(spec.program_id),
                'dispatch_error': str(exc),
            },
            status=409,
        )
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'job': payload, 'campaign': _status(spec)})
    return redirect('manager:target_detail', name=spec.name)


def _image_id(request) -> str | None:
    value = (request.GET.get('image') or '').strip()
    return value or None


def _filter_overlay_payload(payload: dict, *, include_rejects: bool) -> dict:
    """Default responses omit rejects so mosaic switches stay light."""
    if include_rejects:
        return payload
    sources = [src for src in (payload.get('sources') or []) if src.get('passed')]
    out = dict(payload)
    out['sources'] = sources
    out['n_overlay'] = len(sources)
    return out


@require_GET
def reference_preview(request, name=None):
    spec = _spec_or_404(name)
    meta = build_preview(spec.base_dir, image_id=_image_id(request))
    if meta is None:
        raise Http404('Reference preview is not available yet')
    path, content_type, static_url = choose_preview_file(
        meta, accept=request.headers.get('Accept', '')
    )
    # Prefer nginx /static/ so Django is off the hot path.
    if static_url:
        response = redirect(static_url)
        response['Cache-Control'] = 'public, max-age=60'
        return response
    if path is None or not path.is_file():
        raise Http404('Reference preview is not available yet')
    response = FileResponse(open(path, 'rb'), content_type=content_type or 'image/webp')
    response['Cache-Control'] = 'public, max-age=86400'
    return response


@require_GET
def reference_sources(request, name=None):
    spec = _spec_or_404(name)
    image_id = _image_id(request)
    include_rejects = str(request.GET.get('rejects') or '').lower() in {
        '1',
        'true',
        'yes',
        'on',
    }
    payload = ensure_sources_overlay(spec.base_dir, image_id=image_id)
    if payload is None:
        raise Http404('Catalog overlay is not available yet')
    response = JsonResponse(_filter_overlay_payload(payload, include_rejects=include_rejects))
    response['Cache-Control'] = 'private, max-age=300'
    return response


@require_GET
def reference_source_photometry(request, name, index: int):
    spec = _spec_or_404(name)
    payload = source_photometry(spec.base_dir, source_index=int(index), image_id=_image_id(request))
    if payload is None:
        raise Http404('Source photometry is not available')
    response = JsonResponse(payload)
    response['Cache-Control'] = 'private, max-age=120'
    return response


@require_GET
def reference_fits(request, name):
    spec = _spec_or_404(name)
    path = resolve_display_image(spec.base_dir, _image_id(request))
    if path is None or not path.is_file():
        raise Http404('Reference image is not available yet')
    return FileResponse(open(path, 'rb'), as_attachment=True, filename=path.name)


@require_GET
def catalog_hdf5(request, name, stem):
    spec = _spec_or_404(name)
    phot = next((path for path in discover_phot_files(spec.base_dir) if path.stem == stem), None)
    if phot is None:
        raise Http404('Catalog is not available yet')
    stamp = discover_reference_for_phot(phot, spec.base_dir) or discover_reference_image(spec.base_dir)
    stamp_header = read_image_header(stamp) if stamp else {}
    header = {
        'path': str(stamp) if stamp else None,
        'instrument': stamp_header.get('instrument'),
        'filter': stamp_header.get('filter'),
        'photflam': stamp_header.get('photflam'),
        'photplam': stamp_header.get('photplam'),
        'wcs': stamp_header.get('wcs'),
    }
    path = ensure_catalog_hdf5(
        phot,
        base_dir=spec.base_dir,
        reference=stamp,
        wcs=stamp_header.get('wcs'),
        header=header,
    )
    return FileResponse(open(path, 'rb'), as_attachment=True, filename=path.name)
