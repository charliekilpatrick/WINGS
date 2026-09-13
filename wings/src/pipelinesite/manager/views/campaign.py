from __future__ import annotations

from urllib.parse import urlencode

from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from pathlib import Path

from manager.st123.config import find_target, target_config
from manager.st123.gaia import format_wcs_quality, load_gaia_overlay
from manager.st123.hdf5_export import ensure_catalog_hdf5
from manager.st123.inventory import (
    build_campaign_status,
    catalog_sources,
    discover_phot_files,
    discover_reference_image,
    dispatch_availability,
    list_campaign_targets,
    resolve_display_image,
)
from manager.st123.sky import read_image_header
from manager.st123.preview import build_preview
from manager.st123.runner import spawn_job


def _status(target=None):
    spec = target or target_config()
    return build_campaign_status(spec.base_dir, target=spec)


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
    query = (request.GET.get('q') or '').strip()
    targets = list_campaign_targets()
    if query:
        needle = query.lower()
        compact = needle.replace(' ', '')
        targets = [
            row
            for row in targets
            if needle in ' '.join(
                str(row.get(key) or '') for key in ('name', 'display_name', 'host')
            ).lower()
            or compact in (row.get('name') or '').lower().replace(' ', '')
        ]
        if len(targets) == 1:
            return redirect('manager:target_detail', name=targets[0]['name'])
    return render(
        request,
        'campaign/home.html',
        {
            'targets': targets,
            'search_query': query,
            'dispatch': dispatch_availability(),
        },
    )


def target_search(request):
    query = request.GET.get('q', '')
    return redirect(reverse('home_page') + '?' + urlencode({'q': query}))


def target_detail(request, name):
    spec = _spec_or_404(name)
    status = _attach_wcs_quality(_status(spec), spec)
    return render(request, 'campaign/target.html', {'campaign': status})


@require_GET
def campaign_status(request, name=None):
    spec = _spec_or_404(name or request.GET.get('target'))
    return JsonResponse(_status(spec))


@require_POST
def campaign_dispatch(request, name=None):
    spec = _spec_or_404(name or request.POST.get('target') or request.GET.get('target'))
    status = _status(spec)
    rerun_all = request.POST.get('rerun_all') in {'1', 'true', 'on', 'yes'}
    raw = request.POST.get('stages', '').strip()
    if raw:
        stages = [part.strip() for part in raw.split(',') if part.strip()]
    elif rerun_all:
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
            {'campaign': _attach_wcs_quality(_status(spec), spec), 'dispatch_error': str(exc)},
            status=409,
        )
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'job': payload, 'campaign': _status(spec)})
    return redirect('manager:target_detail', name=spec.name)


def _image_id(request) -> str | None:
    value = (request.GET.get('image') or '').strip()
    return value or None


@require_GET
def reference_preview(request, name=None):
    spec = _spec_or_404(name)
    meta = build_preview(spec.base_dir, image_id=_image_id(request))
    if meta is None or not meta.get('png'):
        raise Http404('Reference preview is not available yet')
    return FileResponse(open(meta['png'], 'rb'), content_type='image/png')


@require_GET
def reference_sources(request, name=None):
    spec = _spec_or_404(name)
    meta = build_preview(spec.base_dir, image_id=_image_id(request))
    if meta is None:
        raise Http404('Catalog overlay is not available yet')
    phot_files = discover_phot_files(spec.base_dir)
    stamp = discover_reference_image(spec.base_dir)
    stamp_header = read_image_header(stamp) if stamp else {}
    header = {
        'path': str(stamp) if stamp else meta.get('source'),
        'instrument': stamp_header.get('instrument') or meta.get('instrument'),
        'detector': stamp_header.get('detector') or meta.get('detector'),
        'filter': stamp_header.get('filter') or meta.get('filter'),
        'photflam': stamp_header.get('photflam') or meta.get('photflam'),
        'photplam': stamp_header.get('photplam') or meta.get('photplam'),
        'wcs': stamp_header.get('wcs'),
    }
    sources = []
    if phot_files:
        sources = catalog_sources(
            phot_files[0],
            reference=stamp,
            wcs=stamp_header.get('wcs'),
            header=header,
            base_dir=spec.base_dir,
        )
    gaia = load_gaia_overlay(spec.base_dir, meta.get('wcs'))
    return JsonResponse(
        {
            'reference': meta,
            'sources': sources,
            'n_sources': len(sources),
            'n_passed': sum(1 for src in sources if src['passed']),
            'gaia': gaia,
            'wcs_quality': format_wcs_quality(gaia),
        }
    )


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
    stamp = discover_reference_image(spec.base_dir)
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
