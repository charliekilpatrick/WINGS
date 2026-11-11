"""Post-deploy smoke check for campaign ORM, tags, and key URLs."""

from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from django.urls import reverse


class Command(BaseCommand):
    help = 'Verify WINGS campaign index, status tags, and HTTP endpoints'

    def add_arguments(self, parser):
        parser.add_argument(
            '--program',
            default='18338',
            help='Program ID to exercise (default: 18338)',
        )

    def handle(self, *args, **options):
        from manager.models import Catalog, Program, ScienceImage, Target

        program_id = str(options['program'])
        errors: list[str] = []

        n_programs = Program.objects.count()
        n_targets = Target.objects.count()
        if n_programs < 1:
            errors.append('No Program rows')
        if n_targets < 1:
            errors.append('No Target rows')

        tags = Counter(Target.objects.values_list('status_tag', flat=True))
        self.stdout.write(f'programs={n_programs} targets={n_targets} tags={dict(tags)}')
        self.stdout.write(
            f'images={ScienceImage.objects.count()} catalogs={Catalog.objects.count()}'
        )

        client = Client(HTTP_HOST='burbidge.northwestern.edu')
        checks = [
            ('login', reverse('login'), 200),
            ('api_targets', f"/api/targets/?program={program_id}", 200),
            ('api_empty', f"/api/targets/?program={program_id}&tag=empty_mast", 200),
            ('program', reverse('program_campaign', kwargs={'program_id': program_id}), 302),
        ]
        for label, path, expect in checks:
            response = client.get(path)
            code = response.status_code
            ok = code == expect
            mark = 'OK' if ok else 'FAIL'
            self.stdout.write(f'{mark} {label} {path} -> {code} (want {expect})')
            if not ok:
                errors.append(f'{label}: got {code}, expected {expect}')
            if label.startswith('api') and code == 200:
                body = response.json()
                self.stdout.write(f'  count={body.get("count")}')

        if errors:
            raise CommandError('; '.join(errors))
        self.stdout.write(self.style.SUCCESS('smoke_wings: all checks passed'))
