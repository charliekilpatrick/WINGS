from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from manager.st123.program_sync import sync_program_targets


class Command(BaseCommand):
    help = (
        'Check the STScI visit-status page and MAST for GO program targets, '
        'then add newly archived fields to the campaign table.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--program',
            default='',
            help='HST program ID (default: PIPELINESITE_HST_PROGRAM_ID).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would be written without updating the registry.',
        )

    def handle(self, *args, **options):
        program = (options.get('program') or '').strip() or str(
            getattr(settings, 'HST_PROGRAM_ID', '18338')
        )
        try:
            result = sync_program_targets(
                program=program,
                dry_run=bool(options.get('dry_run')),
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        n_ready = result.get('n_ready') or 0
        added = result.get('added') or []
        self.stdout.write(
            f"GO {result.get('program_id')}: "
            f"{result.get('n_visits', 0)} visits, "
            f"{result.get('n_observed', 0)} observed, "
            f"{result.get('n_mast', 0)} MAST images, "
            f"{n_ready} ready"
        )
        if added:
            self.stdout.write(self.style.SUCCESS('Added: ' + ', '.join(added)))
        elif options.get('dry_run'):
            self.stdout.write('Dry run; registry not written.')
        else:
            self.stdout.write('No new targets with STScI-observed visits and MAST data.')
