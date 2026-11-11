"""Lightweight JSON API for campaign targets."""

from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from manager.st123.inventory import list_campaign_targets
from manager.st123.status_tags import TAG_LABELS


@require_GET
def api_targets(request):
    program = (request.GET.get('program') or '').strip() or None
    tag = (request.GET.get('tag') or '').strip().lower() or None
    role = (request.GET.get('role') or '').strip().lower() or None
    query = (request.GET.get('q') or '').strip().lower()
    rows = list_campaign_targets(program)
    if tag:
        rows = [row for row in rows if (row.get('status_tag') or '') == tag]
    if role in {'prime', 'parallel'}:
        rows = [row for row in rows if (row.get('field_role') or 'prime') == role]
    if query:
        compact = query.replace(' ', '')
        rows = [
            row
            for row in rows
            if query
            in ' '.join(
                str(row.get(key) or '')
                for key in ('name', 'display_name', 'host', 'field_role', 'status', 'sn_type')
            ).lower()
            or compact in (row.get('name') or '').lower().replace(' ', '')
        ]
    return JsonResponse(
        {
            'count': len(rows),
            'tags': TAG_LABELS,
            'results': [
                {
                    'name': row.get('name'),
                    'display_name': row.get('display_name'),
                    'program_id': row.get('program_id'),
                    'host': row.get('host'),
                    'field_role': row.get('field_role'),
                    'sn_type': row.get('sn_type'),
                    'ra': row.get('ra'),
                    'dec': row.get('dec'),
                    'n_images': row.get('n_images'),
                    'n_done': row.get('n_done'),
                    'n_stages': row.get('n_stages'),
                    'status': row.get('status'),
                    'status_tag': row.get('status_tag'),
                    'job_state': row.get('job_state'),
                    'new_data': row.get('new_data'),
                    'n_new_obs': row.get('n_new_obs'),
                    'has_catalog': row.get('has_catalog'),
                    'has_reference': row.get('has_reference'),
                    'distance_display': row.get('distance_display'),
                }
                for row in rows
            ],
        }
    )
