from __future__ import annotations

from collections import Counter

from django.http import Http404
from django.shortcuts import redirect, render

from manager.st123.inventory import dispatch_availability, list_campaign_targets
from manager.st123.programs import find_program, list_program_specs
from manager.st123.status_tags import TAG_LABELS


def _filter_targets(targets, query: str):
    needle = query.lower()
    compact = needle.replace(' ', '')
    return [
        row
        for row in targets
        if needle in ' '.join(
            str(row.get(key) or '')
            for key in ('name', 'display_name', 'host', 'field_role', 'status', 'sn_type')
        ).lower()
        or compact in (row.get('name') or '').lower().replace(' ', '')
    ]


def _apply_list_filters(targets, *, tag: str = '', role: str = ''):
    rows = list(targets)
    if tag:
        rows = [row for row in rows if (row.get('status_tag') or '') == tag]
    if role in {'prime', 'parallel'}:
        rows = [row for row in rows if (row.get('field_role') or 'prime') == role]
    return rows


def program_summaries() -> list[dict]:
    rows = []
    for spec in list_program_specs():
        targets = list_campaign_targets(spec.program_id)
        rows.append(
            {
                'program_id': spec.program_id,
                'short_name': spec.short_name,
                'title': spec.title,
                'pi': spec.pi,
                'institution': spec.institution,
                'cycle': spec.cycle,
                'orbits': spec.orbits,
                'status': spec.status,
                'url': spec.url,
                'n_targets': len(targets),
                'n_images': sum(int(row.get('n_images') or 0) for row in targets),
                'n_complete': sum(
                    1 for row in targets if row.get('status_tag') == 'complete'
                ),
                'n_empty_mast': sum(
                    1 for row in targets if row.get('status_tag') == 'empty_mast'
                ),
                'n_new_data': sum(1 for row in targets if row.get('new_data')),
            }
        )
    return rows


def programs_home(request):
    query = (request.GET.get('q') or '').strip()
    if query:
        matches = _filter_targets(list_campaign_targets(), query)
        if len(matches) == 1:
            return redirect('manager:target_detail', name=matches[0]['name'])
        return render(
            request,
            'programs/home.html',
            {
                'programs': program_summaries(),
                'search_query': query,
                'search_targets': matches,
            },
        )
    return render(
        request,
        'programs/home.html',
        {
            'programs': program_summaries(),
            'search_query': '',
            'search_targets': [],
        },
    )


def program_campaign(request, program_id):
    spec = find_program(program_id)
    if spec is None:
        raise Http404(f'Unknown program {program_id}')
    query = (request.GET.get('q') or '').strip()
    tag = (request.GET.get('tag') or '').strip().lower()
    role = (request.GET.get('role') or '').strip().lower()
    all_targets = list_campaign_targets(spec.program_id, refresh_distances=True)
    tag_counts = Counter(row.get('status_tag') or 'pending' for row in all_targets)
    tag_options = [
        {'key': key, 'label': label, 'count': tag_counts.get(key, 0)}
        for key, label in TAG_LABELS.items()
    ]
    targets = all_targets
    if query:
        targets = _filter_targets(targets, query)
        if len(targets) == 1 and not tag and not role:
            return redirect('manager:target_detail', name=targets[0]['name'])
    targets = _apply_list_filters(targets, tag=tag, role=role)
    return render(
        request,
        'campaign/home.html',
        {
            'program': spec,
            'targets': targets,
            'search_query': query,
            'filter_tag': tag,
            'filter_role': role,
            'tag_options': tag_options,
            'dispatch': dispatch_availability(),
            'n_new_data': sum(1 for row in all_targets if row.get('new_data')),
            'n_empty_mast': tag_counts.get('empty_mast', 0),
        },
    )
