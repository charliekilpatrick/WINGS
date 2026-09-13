from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

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
    help = 'Create unmanaged wpipe tables and seed an example pipeline for local exploration.'

    def handle(self, *args, **options):
        self._create_tables()
        if Users.objects.filter(name='charlie').exists():
            self.stdout.write('Demo data already present; leaving existing rows in place.')
        else:
            self._seed()
            self.stdout.write(self.style.SUCCESS('Seeded example pipeline, jobs, tasks, and events.'))
        self._ensure_admin()

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
        user = Users.objects.create(name='charlie', timestamp=now)
        Users.objects.create(name='demo', timestamp=now - timedelta(days=2))

        node = Nodes.objects.create(
            name='local-dev',
            timestamp=now,
            int_ip='127.0.0.1',
            ext_ip='127.0.0.1',
        )

        pipe_owner = self._new_dpowner(now, 'pipeline')
        pipeline = Pipelines.objects.create(
            id=pipe_owner,
            name='example_photometry',
            pipe_root='/tmp/wings-demo/example_photometry',
            software_root='/tmp/wings-demo/example_photometry/software',
            input_root='/tmp/wings-demo/example_photometry/input',
            data_root='/tmp/wings-demo/example_photometry/data',
            config_root='/tmp/wings-demo/example_photometry/config',
            description='Example WINGS-like photometry pipeline for local exploration.',
            user=user,
        )

        task_specs = [
            ('prepare_inputs', 1, 12.5, 0),
            ('run_stips', 3, 340.0, 0),
            ('run_dolphot', 2, 1280.4, 1),
            ('make_catalog', 1, 45.2, 0),
        ]
        tasks = {}
        for name, nruns, run_time, exclusive in task_specs:
            tasks[name] = Tasks.objects.create(
                name=name,
                timestamp=now - timedelta(hours=6),
                nruns=nruns,
                run_time=run_time,
                is_exclusive=exclusive,
                pipeline=pipeline,
            )

        input_owner = self._new_dpowner(now, 'input')
        pipe_input = Inputs.objects.create(
            id=input_owner,
            name='m31_field',
            rawspath='/tmp/wings-demo/example_photometry/input/raw',
            confpath='/tmp/wings-demo/example_photometry/input/conf',
            pipeline=pipeline,
        )

        target_owner = self._new_optowner(now, 'target')
        target = Targets.objects.create(
            id=target_owner,
            name='NGC_test_field',
            datapath='/tmp/wings-demo/example_photometry/data/NGC_test_field',
            dataraws='/tmp/wings-demo/example_photometry/input/raw/NGC_test_field',
            input=pipe_input,
        )

        config_owner = self._new_dpowner(now, 'configuration')
        config = Configurations.objects.create(
            id=config_owner,
            name='default_config',
            datapath='/tmp/wings-demo/example_photometry/data/NGC_test_field/default_config',
            confpath='/tmp/wings-demo/example_photometry/config/default.conf',
            rawpath='/tmp/wings-demo/example_photometry/input/raw',
            logpath='/tmp/wings-demo/example_photometry/data/NGC_test_field/logs',
            procpath='/tmp/wings-demo/example_photometry/data/NGC_test_field/proc',
            description='Default configuration for the example field.',
            target=target,
        )
        Parameters.objects.create(name='FILTER', value='F129', timestamp=now, config=config)
        Parameters.objects.create(name='NEXP', value='4', timestamp=now, config=config)

        conf_dp_owner = self._new_optowner(now, 'dataproduct')
        Dataproducts.objects.create(
            id=conf_dp_owner,
            filename='default.conf',
            relativepath='/tmp/wings-demo/example_photometry/config',
            suffix='conf',
            data_type='text',
            subtype='pipeline',
            group=DataProductGroups.CONFIGURATION.value,
            filtername='F129',
            ra=10.6847,
            dec=41.2690,
            pointing_angle=0.0,
            dpowner=pipe_owner,
        )

        Masks.objects.create(
            name='prepare_done',
            timestamp=now,
            source='event',
            value='1',
            task=tasks['run_stips'],
        )

        chain = [
            ('start', 'new', 'prepare_inputs', JobStates.COMPLETED.value[0], now - timedelta(hours=5), now - timedelta(hours=4, minutes=50)),
            ('inputs_ready', 'ok', 'run_stips', JobStates.COMPLETED.value[0], now - timedelta(hours=4, minutes=40), now - timedelta(hours=3)),
            ('stips_done', 'ok', 'run_dolphot', JobStates.INITIALIZED.value[0], now - timedelta(hours=2), None),
            ('need_catalog', 'pending', 'make_catalog', JobStates.SUBMITTED.value[0], None, None),
        ]

        parent_job = None
        for event_name, tag, task_name, state, start, end in chain:
            event_owner = self._new_optowner(now, 'event')
            event = Events.objects.create(
                id=event_owner,
                name=event_name,
                tag=tag,
                jargs='{}',
                value=task_name,
                parent_job=parent_job,
            )
            job_owner = self._new_optowner(now, 'job')
            parent_job = Jobs.objects.create(
                id=job_owner,
                attempt=1,
                state=state,
                starttime=start,
                endtime=end,
                node=node,
                config=config,
                task=tasks[task_name],
                firing_event=event,
            )

        failed_event_owner = self._new_optowner(now, 'event')
        failed_event = Events.objects.create(
            id=failed_event_owner,
            name='stips_retry',
            tag='error',
            jargs='{"attempt": 2}',
            value='run_stips',
            parent_job=Jobs.objects.filter(task=tasks['prepare_inputs']).first(),
        )
        Jobs.objects.create(
            id=self._new_optowner(now, 'job'),
            attempt=2,
            state=JobStates.ERROR.value[0],
            starttime=now - timedelta(hours=4, minutes=30),
            endtime=now - timedelta(hours=4, minutes=28),
            node=node,
            config=config,
            task=tasks['run_stips'],
            firing_event=failed_event,
        )
