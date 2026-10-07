"""Require a site account for every page except login and static files."""

from __future__ import annotations

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


_EXEMPT_PREFIXES = (
    '/static/',
    '/accounts/login/',
    '/accounts/logout/',
    '/admin/',
)


class LoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            return self.get_response(request)
        path = request.path
        if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            return self.get_response(request)
        login_url = getattr(settings, 'LOGIN_URL', None) or reverse('login')
        return redirect(f'{login_url}?next={request.get_full_path()}')
