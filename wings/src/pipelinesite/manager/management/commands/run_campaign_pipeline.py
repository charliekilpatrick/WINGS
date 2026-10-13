from django.core.management.base import BaseCommand, CommandError

from manager.st123.config import STAGES, campaign_targets
from manager.st123.programs import find_program, list_program_specs
from manager.st123.runner import run_stages


class Command(BaseCommand):
    help = (
        'Run st123 stages for every campaign target, one target at a time. '
        'The website reads status from each target directory as stages finish.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--program',
            action='append',
            default=[],
            help='Limit to one HST program ID. Repeat to run several. Default: 18338 then 18440.',
        )
        parser.add_argument(
            '--stages',
            default=','.join(spec.key for spec in STAGES),
            help='Comma-separated stage keys (default: the full pipeline, including download).',
        )
        parser.add_argument(
            '--remaining-only',
            action='store_true',
            help='Skip stages that already have products on disk.',
        )
        parser.add_argument(
            '--stop-on-error',
            action='store_true',
            help='Stop after the first failing target (default: continue).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print the target list without running reductions.',
        )

    def handle(self, *args, **options):
        from manager.st123.inventory import infer_stages, remaining_stages

        raw = options.get('program') or []
        if isinstance(raw, str):
            raw = [raw]
        programs = [str(item).strip() for item in raw if str(item).strip()]
        if programs:
            unknown = [pid for pid in programs if find_program(pid) is None]
            if unknown:
                raise CommandError('Unknown program(s): ' + ', '.join(unknown))
        else:
            programs = [spec.program_id for spec in list_program_specs()]

        keys = [part.strip() for part in str(options.get('stages') or '').split(',') if part.strip()]
        known = {spec.key for spec in STAGES}
        bad = [key for key in keys if key not in known]
        if bad:
            raise CommandError('Unknown stages: ' + ', '.join(bad))
        if not keys:
            keys = [spec.key for spec in STAGES]

        targets = []
        seen = set()
        for pid in programs:
            for spec in campaign_targets(pid):
                if spec.name in seen:
                    continue
                seen.add(spec.name)
                targets.append(spec)
        if not targets:
            raise CommandError('No campaign targets found.')

        dry_run = bool(options.get('dry_run'))
        remaining_only = bool(options.get('remaining_only'))
        stop_on_error = bool(options.get('stop_on_error'))
        failed = []
        self.stdout.write(f'{len(targets)} target(s); stages: {", ".join(keys)}')
        for index, spec in enumerate(targets, start=1):
            run_keys = keys
            if remaining_only:
                run_keys = [key for key in remaining_stages(infer_stages(spec.base_dir)) if key in keys]
            label = f'[{index}/{len(targets)}] GO {spec.program_id} {spec.name}'
            if not run_keys:
                self.stdout.write(f'{label}: already complete')
                continue
            self.stdout.write(f'{label}: {", ".join(run_keys)}')
            if dry_run:
                continue
            try:
                run_stages(run_keys, target=spec)
            except Exception as exc:
                failed.append((spec.name, str(exc)))
                self.stderr.write(self.style.ERROR(f'{label} failed: {exc}'))
                if stop_on_error:
                    raise CommandError(f'{spec.name} failed: {exc}') from exc
        if dry_run:
            self.stdout.write('Dry run; no stages executed.')
            return
        if failed:
            self.stdout.write(self.style.ERROR(f'Finished with {len(failed)} failure(s).'))
            for name, message in failed:
                self.stdout.write(f'  {name}: {message}')
            raise CommandError(f'{len(failed)} target(s) failed.')
        self.stdout.write(self.style.SUCCESS(f'Finished {len(targets)} target(s).'))
