"""Gunicorn / nginx serve settings. Import after setting PIPELINESITE_SERVE=1."""

from __future__ import annotations

import os
from pathlib import Path

# Ensure demo SQLite path before importing base settings.
os.environ.setdefault('PIPELINESITE_DEMO', '1')
os.environ.setdefault('PIPELINESITE_SERVE', '1')

from .settings import *  # noqa: F401,F403

SERVE_MODE = True
DEBUG = False

_secret_file = Path(
    os.environ.get(
        'PIPELINESITE_SECRET_KEY_FILE',
        '/data/ckilpatrick/HST/.pipelinesite/django_secret_key',
    )
)
_env_secret = os.environ.get('PIPELINESITE_SECRET_KEY', '').strip()
if _env_secret:
    SECRET_KEY = _env_secret
elif _secret_file.is_file():
    SECRET_KEY = _secret_file.read_text().strip()
else:
    _secret_file.parent.mkdir(parents=True, exist_ok=True)
    SECRET_KEY = os.urandom(48).hex()
    _secret_file.write_text(SECRET_KEY)
    try:
        _secret_file.chmod(0o600)
    except OSError:
        pass

ALLOWED_HOSTS = [
    'localhost',
    '127.0.0.1',
    '[::1]',
    'burbidge',
    'burbidge.northwestern.edu',
    '165.124.148.146',
]
ALLOWED_HOSTS.extend(
    host.strip()
    for host in os.environ.get('PIPELINESITE_ALLOWED_HOSTS', '').split(',')
    if host.strip()
)

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = os.environ.get('PIPELINESITE_HTTPS', '') == '1'
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_TRUSTED_ORIGINS = [
    'https://burbidge.northwestern.edu',
    'http://burbidge.northwestern.edu',
    'http://127.0.0.1',
    'http://localhost',
]
