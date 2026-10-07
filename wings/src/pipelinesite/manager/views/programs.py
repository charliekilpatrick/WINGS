from __future__ import annotations

from django.http import Http404
from django.shortcuts import redirect, render

from manager.st123.inventory import dispatch_availability, list_campaign_targets
from manager.st123.programs import find_program, list_program_specs


def _filter_targets(targets, query: str):
    needle = query.lower()
    compact = needle.replace(' ', '')
    return [
        row
        for row in targets
        if needle in ' '.join(
            str(row.get(key) or '') for key in ('name', 'display_name', 'host', 'field_role')
        ).lower()
        or compact in (row.get('name') or '').lower().replace(' ', '')
    ]


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
                'n_complete': sum(1 for row in targets if row.get('job_state') == 'completed'),
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
    targets = list_campaign_targets(spec.program_id, refresh_distances=True)
    if query:
        targets = _filter_targets(targets, query)
        if len(targets) == 1:
            return redirect('manager:target_detail', name=targets[0]['name'])
    return render(
        request,
        'campaign/home.html',
        {
            'program': spec,
            'targets': targets,
            'search_query': query,
            'dispatch': dispatch_availability(),
        },
    )
