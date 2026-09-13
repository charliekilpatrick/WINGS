from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from manager.st123.config import STAGES, target_config
from pipelinesite.models import (
    Configurations,
    Dataproducts,
    Dpowners,
    Events,
    Inputs,
    Jobs,
    Masks,
    Nodes,
    Optowners,
    Parameters,
    Pipelines,
    Targets,
    Tasks,
    Users,
)
from pipelinesite.utils import DataProductGroups, JobStates


WPIPE_MODELS = [
    Users,
    Nodes,
    Dpowners,
    Optowners,
    Pipelines,
    Tasks,
    Inputs,
    Targets,
    Configurations,
    Parameters,
    Dataproducts,
    Masks,
]


class Command(BaseCommand):
    help = 'Create unmanaged wpipe tables and seed the st123 example campaign.'

    def handle(self, *args, **options):
        self._create_tables()
        self._purge_demo_rows()
        pipeline = Pipelines.objects.filter(name='st123').first()
        expected = {spec.key for spec in STAGES}
        have = set()
        if pipeline is not None:
            have = set(Tasks.objects.filter(pipeline=pipeline).values_list('name', flat=True))
        if pipeline is not None and expected <= have:
            self.stdout.write('st123 example campaign already present; leaving existing rows in place.')
        else:
            if pipeline is not None:
                Tasks.objects.filter(pipeline=pipeline).delete()
                pipeline.delete()
            self._seed()
            self.stdout.write(self.style.SUCCESS('Seeded st123 example campaign for SN 2026dix.'))
        self._ensure_admin()
        self._sync_stage_runtimes()

    def _purge_demo_rows(self):
        from manager.local_scope import is_local_pipeline

        removed = 0
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA foreign_keys=OFF')
        try:
            for pipe in list(Pipelines.objects.all()):
                if is_local_pipeline(pipe):
                    continue
                tasks = Tasks.objects.filter(pipeline=pipe)
                jobs = Jobs.objects.filter(task__in=tasks)
                Events.objects.filter(parent_job__in=jobs).delete()
                firing_ids = list(jobs.values_list('firing_event_id', flat=True))
                jobs.delete()
                Events.objects.filter(id__in=[eid for eid in firing_ids if eid]).delete()
                Masks.objects.filter(task__in=tasks).delete()
                inputs = Inputs.objects.filter(pipeline=pipe)
                targets = Targets.objects.filter(input__in=inputs)
                configs = Configurations.objects.filter(target__in=targets)
                Parameters.objects.filter(config__in=configs).delete()
                Jobs.objects.filter(config__in=configs).delete()
                configs.delete()
                targets.delete()
                inputs.delete()
                tasks.delete()
                pipe.delete()
                removed += 1
        finally:
            with connection.cursor() as cursor:
                cursor.execute('PRAGMA foreign_keys=ON')
        if removed:
            self.stdout.write(f'Removed {removed} non-local demo pipeline(s).')

    def _sync_stage_runtimes(self):
        from manager.st123.inventory import infer_stages

        pipeline = Pipelines.objects.filter(name='st123').first()
        if pipeline is None:
            return
        target = target_config()
        by_key = {row['key']: row for row in infer_stages(target.base_dir)}
        for task in Tasks.objects.filter(pipeline=pipeline):
            row = by_key.get(task.name)
            if not row or row.get('seconds') is None:
                continue
            task.run_time = float(row['seconds'])
            if row.get('state') == 'completed' and task.nruns == 0:
                task.nruns = 1
            task.save(update_fields=['run_time', 'nruns'])

    def _create_tables(self):
        existing = set()
        with connection.cursor() as cursor:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            existing = {row[0] for row in cursor.fetchall()}

        missing = [model for model in WPIPE_MODELS + [Jobs, Events] if model._meta.db_table not in existing]
        if not missing:
            return

        with connection.schema_editor() as editor:
            for model in WPIPE_MODELS:
                if model._meta.db_table not in existing:
                    editor.create_model(model)
            self._create_jobs_and_events(editor, existing)

    def _create_jobs_and_events(self, editor, existing):
        parent_job = Events._meta.get_field('parent_job')
        if Events._meta.db_table not in existing:
            Events._meta.local_fields.remove(parent_job)
            try:
                editor.create_model(Events)
            finally:
                Events._meta.local_fields.append(parent_job)
        if Jobs._meta.db_table not in existing:
            editor.create_model(Jobs)
        if Events._meta.db_table not in existing:
            editor.add_field(Events, parent_job)

    def _ensure_admin(self):
        auth_user = get_user_model()
        if not auth_user.objects.filter(username='admin').exists():
            auth_user.objects.create_superuser('admin', 'admin@example.com', 'admin')
            self.stdout.write('Created Django admin user admin / admin')

    def _new_dpowner(self, now, type_name):
        return Dpowners.objects.create(timestamp=now, type=type_name)

    def _new_optowner(self, now, type_name):
        return Optowners.objects.create(timestamp=now, type=type_name)

    def _seed(self):
        now = timezone.now()
        target = target_config()
        user, _ = Users.objects.get_or_create(name='charlie', defaults={'timestamp': now})
        node, _ = Nodes.objects.get_or_create(
            name='local-st123',
            defaults={'timestamp': now, 'int_ip': '127.0.0.1', 'ext_ip': '127.0.0.1'},
        )

        pipe_owner = self._new_dpowner(now, 'pipeline')
        pipeline = Pipelines.objects.create(
            id=pipe_owner,
            name='st123',
            pipe_root=str(target.base_dir),
            software_root='/data/ckilpatrick/st123',
            input_root=str(target.base_dir / 'download'),
            data_root=str(target.base_dir),
            config_root=str(target.base_dir / '.pipelinesite'),
            description='',
            user=user,
        )

        tasks = {}
        for spec in STAGES:
            tasks[spec.key] = Tasks.objects.create(
                name=spec.key,
                timestamp=now - timedelta(hours=6),
                nruns=0,
                run_time=0.0,
                is_exclusive=0,
                pipeline=pipeline,
            )
        for index, spec in enumerate(STAGES[:-1]):
            Masks.objects.create(
                name=f'{spec.key}_done',
                timestamp=now,
                source='event',
                value='1',
                task=tasks[STAGES[index + 1].key],
            )

        input_owner = self._new_dpowner(now, 'input')
        pipe_input = Inputs.objects.create(
            id=input_owner,
            name=target.name,
            rawspath=str(target.base_dir / 'download'),
            confpath=str(target.base_dir / '.pipelinesite'),
            pipeline=pipeline,
        )

        target_owner = self._new_optowner(now, 'target')
        db_target = Targets.objects.create(
            id=target_owner,
            name=target.name,
            datapath=str(target.base_dir),
            dataraws=str(target.base_dir / 'download'),
            input=pipe_input,
        )

        config_owner = self._new_dpowner(now, 'configuration')
        config = Configurations.objects.create(
            id=config_owner,
            name='default',
            datapath=str(target.base_dir),
            confpath=str(target.base_dir / '.pipelinesite'),
            rawpath=str(target.base_dir / 'download'),
            logpath=str(target.base_dir / 'logs'),
            procpath=str(target.base_dir / 'reduction'),
            description=target.notes,
            target=db_target,
        )
        Parameters.objects.create(name='RA', value=str(target.ra), timestamp=now, config=config)
        Parameters.objects.create(name='DEC', value=str(target.dec), timestamp=now, config=config)
        Parameters.objects.create(name='TELESCOPE', value=target.telescope, timestamp=now, config=config)
        Parameters.objects.create(
            name='INSTRUMENTS',
            value=','.join(target.instruments),
            timestamp=now,
            config=config,
        )

        conf_dp_owner = self._new_optowner(now, 'dataproduct')
        Dataproducts.objects.create(
            id=conf_dp_owner,
            filename='campaign.json',
            relativepath=str(target.base_dir / '.pipelinesite'),
            suffix='json',
            data_type='text',
            subtype='pipeline',
            group=DataProductGroups.CONFIGURATION.value,
            filtername='',
            ra=target.ra,
            dec=target.dec,
            pointing_angle=0.0,
            dpowner=pipe_owner,
        )

        # Record any already-finished stages as completed historical jobs.
        from manager.st123.inventory import infer_stages

        parent_job = None
        for row in infer_stages(target.base_dir):
            if row['state'] != 'completed':
                continue
            event = Events.objects.create(
                id=self._new_optowner(now, 'event'),
                name=f'{row["key"]}_done',
                tag='ok',
                jargs='{}',
                value=row['key'],
                parent_job=parent_job,
            )
            start = now - timedelta(hours=2)
            end = now - timedelta(hours=1)
            parent_job = Jobs.objects.create(
                id=self._new_optowner(now, 'job'),
                attempt=1,
                state=JobStates.COMPLETED.value[0],
                starttime=start,
                endtime=end,
                node=node,
                config=config,
                task=tasks[row['key']],
                firing_event=event,
            )
