from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render

from manager.st123.config import campaign_targets
from manager.st123.program_sync import add_manual_target
from manager.st123.programs import list_program_specs
from manager.st123.sky import parse_sky_pair


def _staff_required(request):
    if not request.user.is_authenticated:
        return redirect('login')
    if not request.user.is_staff:
        return HttpResponseForbidden('Admin accounts only.')
    return None


@login_required
def site_admin(request):
    denied = _staff_required(request)
    if denied is not None:
        return denied
    User = get_user_model()
    if request.method == 'POST':
        action = request.POST.get('action') or ''
        try:
            if action == 'add_user':
                _add_user(request)
            elif action == 'update_user':
                _update_user(request)
            elif action == 'add_target':
                _add_target(request)
            else:
                messages.error(request, 'Unknown admin action.')
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect('site_admin')
    users = User.objects.order_by('-is_staff', 'username')
    targets = [
        {
            'name': spec.name,
            'display_name': spec.display_name,
            'program_id': spec.program_id,
            'host': spec.host,
            'field_role': spec.field_role,
            'source': 'manual' if 'admin console' in (spec.notes or '').lower() else '',
        }
        for spec in campaign_targets()
    ]
    return render(
        request,
        'admin/console.html',
        {
            'admin_users': users,
            'admin_targets': targets,
            'programs': list_program_specs(),
        },
    )


def _add_user(request):
    User = get_user_model()
    username = (request.POST.get('username') or '').strip()
    email = (request.POST.get('email') or '').strip()
    password = request.POST.get('password') or ''
    is_admin = request.POST.get('is_admin') == '1'
    if not username:
        raise ValueError('Username is required.')
    if not password:
        raise ValueError('Password is required.')
    if User.objects.filter(username=username).exists():
        raise ValueError(f'User {username} already exists.')
    user = User.objects.create_user(username=username, email=email, password=password)
    user.is_staff = is_admin
    if is_admin:
        user.is_superuser = True
    user.save()
    messages.success(request, f'Added user {username}.')


def _update_user(request):
    User = get_user_model()
    username = (request.POST.get('username') or '').strip()
    user = User.objects.filter(username=username).first()
    if user is None:
        raise ValueError(f'Unknown user {username}.')
    if user == request.user and request.POST.get('active') == '0':
        raise ValueError('You cannot deactivate your own account.')
    user.is_active = request.POST.get('active') == '1'
    user.is_staff = request.POST.get('is_admin') == '1'
    if user.is_staff:
        user.is_superuser = True
    user.save()
    messages.success(request, f'Updated {username}.')


def _add_target(request):
    sky = parse_sky_pair(request.POST.get('ra'), request.POST.get('dec'))
    if sky is None:
        raise ValueError('Enter RA and Dec as decimal degrees or sexagesimal.')
    try:
        radius = float(request.POST.get('radius_arcmin') or 5.0)
    except ValueError as exc:
        raise ValueError('Search radius must be a number.') from exc
    record = add_manual_target(
        program_id=request.POST.get('program_id') or '',
        name=request.POST.get('name') or '',
        display_name=request.POST.get('display_name') or '',
        host=request.POST.get('host') or '',
        ra=sky[0],
        dec=sky[1],
        field_role=request.POST.get('field_role') or 'prime',
        radius_arcmin=radius,
        notes=request.POST.get('notes') or '',
    )
    messages.success(request, f'Added target {record["name"]} to GO {record["program_id"]}.')
