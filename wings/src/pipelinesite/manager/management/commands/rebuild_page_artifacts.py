"""Prebuild page_inventory.json / preview PNGs (and sync ScienceImage/Catalog)."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from manager.st123.config import campaign_targets
from manager.st123.inventory import rebuild_page_artifacts


class Command(BaseCommand):
    help = 'Rebuild page inventory + preview artifacts for campaign targets'

    def add_arguments(self, parser):
        parser.add_argument(
            '--program',
            action='append',
            dest='programs',
            help='Limit to one or more program IDs (default: all)',
        )
        parser.add_argument(
            '--target',
            action='append',
            dest='targets',
            help='Limit to one or more target names',
        )
        parser.add_argument(
            '--no-preview',
            action='store_true',
            help='Skip PNG preview rebuild',
        )
        parser.add_argument(
            '--only-missing',
            action='store_true',
            help='Skip targets that already have a fresh page_inventory.json',
        )

    def handle(self, *args, **options):
        from manager.st123.inventory import load_page_inventory

        programs = options.get('programs') or [None]
        names = set(options.get('targets') or [])
        include_preview = not options.get('no_preview')
        only_missing = bool(options.get('only_missing'))
        done = 0
        skipped = 0
        for program in programs:
            specs = list(campaign_targets(program))
            if names:
                specs = [spec for spec in specs if spec.name in names]
            for spec in specs:
                if only_missing and load_page_inventory(spec.base_dir) is not None:
                    skipped += 1
                    continue
                try:
                    rebuild_page_artifacts(spec.base_dir, include_preview=include_preview)
                    done += 1
                    self.stdout.write(f'OK {spec.name}')
                except Exception as exc:
                    self.stderr.write(f'FAIL {spec.name}: {exc}')
        self.stdout.write(
            self.style.SUCCESS(f'Rebuilt={done} skipped={skipped}')
        )
