from django.core.management.base import BaseCommand, CommandError

from manager.st123.config import STAGES, find_target, target_config
from manager.st123.runner import run_stages


class Command(BaseCommand):
    help = 'Run one or more st123 stages for a campaign target.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--stages',
            required=True,
            help='Comma-separated stage keys: ' + ', '.join(spec.key for spec in STAGES),
        )
        parser.add_argument(
            '--target',
            default='',
            help='Campaign target name (default: the configured example target).',
        )

    def handle(self, *args, **options):
        keys = [part.strip() for part in options['stages'].split(',') if part.strip()]
        known = {spec.key for spec in STAGES}
        unknown = [key for key in keys if key not in known]
        if unknown:
            raise CommandError(f'Unknown stages: {", ".join(unknown)}')
        name = (options.get('target') or '').strip()
        target = find_target(name) if name else target_config()
        if target is None:
            raise CommandError(f'Unknown target {name}')
        try:
            run_stages(keys, target=target)
        except Exception as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS(f'Finished {target.name}: ' + ', '.join(keys)))
