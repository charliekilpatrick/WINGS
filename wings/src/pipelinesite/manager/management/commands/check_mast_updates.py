from django.core.management.base import BaseCommand, CommandError

from manager.st123.mast_updates import check_all_programs, check_program_updates
from manager.st123.programs import list_program_specs


class Command(BaseCommand):
    help = (
        'Query MAST for GO 18338 and GO 18440 and flag campaign pages when '
        'new program data are available to process.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--program',
            action='append',
            default=[],
            help='Limit to one HST program ID. Repeat to check several. Default: both.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print the comparison without writing mast_updates.json.',
        )

    def handle(self, *args, **options):
        raw = options.get('program') or []
        if isinstance(raw, str):
            raw = [raw]
        programs = [str(item).strip() for item in raw if str(item).strip()]
        if not programs:
            programs = [spec.program_id for spec in list_program_specs()]
        dry_run = bool(options.get('dry_run'))
        try:
            results = [check_program_updates(pid, dry_run=dry_run) for pid in programs]
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        if not results:
            results = check_all_programs(dry_run=dry_run)
        for result in results:
            n_new = result.get('n_new_targets') or 0
            line = (
                f"GO {result.get('program_id')}: "
                f"{result.get('n_mast', 0)} MAST observations, "
                f"{n_new} target(s) with new data"
            )
            if n_new:
                names = [
                    row.get('display_name') or row.get('name')
                    for row in result.get('targets') or []
                    if row.get('new_available')
                ]
                self.stdout.write(self.style.WARNING(line))
                self.stdout.write('  ' + ', '.join(str(name) for name in names if name))
            else:
                self.stdout.write(line)
            if dry_run:
                self.stdout.write('Dry run; mast_updates.json not written.')
