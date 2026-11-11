"""Seed Program / Target / StageRun from APT catalogs and on-disk status.json."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from manager.st123.campaign_index import ingest_all


class Command(BaseCommand):
    help = 'Ingest campaign Program/Target/StageRun rows from APT + status.json'

    def add_arguments(self, parser):
        parser.add_argument(
            '--program',
            action='append',
            dest='programs',
            help='Limit to one or more program IDs (default: all)',
        )

    def handle(self, *args, **options):
        programs = options.get('programs')
        if not programs:
            programs = [None]
        elif isinstance(programs, str):
            programs = [programs]
        total_targets = 0
        n_programs = 0
        for program in programs:
            stats = ingest_all(program)
            n_programs = max(n_programs, stats['programs'])
            total_targets += stats['targets']
            label = program or 'all'
            self.stdout.write(
                self.style.SUCCESS(
                    f'[{label}] programs={stats["programs"]} targets={stats["targets"]}'
                )
            )
        self.stdout.write(
            self.style.SUCCESS(f'Done. programs≈{n_programs} targets={total_targets}')
        )
