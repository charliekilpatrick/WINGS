import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from manager.models import Program, StageRun, Target
from manager.st123.campaign_index import ingest_all, list_targets_from_db, upsert_target_from_spec
from manager.st123.config import TargetSpec
from manager.st123.inventory import list_campaign_targets


def _spec(name='ngc0157', ra=8.6, dec=-8.4, base_dir=None, program_id='18338'):
    root = Path(base_dir or '/tmp/ngc0157')
    return TargetSpec(
        name=name,
        display_name=name.upper(),
        host='NGC 157',
        sn_type='',
        ra=ra,
        dec=dec,
        ra_sex='',
        dec_sex='',
        radius_arcmin=5.0,
        instruments=('ACS', 'WFC3'),
        telescope='hst',
        base_dir=root,
        notes='',
        program_id=program_id,
        field_role='prime',
    )


class CampaignIndexTests(TestCase):
    def test_ingest_and_list_from_orm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'ngc0157'
            (root / '.pipelinesite').mkdir(parents=True)
            (root / '.pipelinesite' / 'status.json').write_text(
                json.dumps(
                    {
                        'state': 'completed',
                        'n_images': 4,
                        'stages': {
                            'download': {
                                'state': 'completed',
                                'started_at': '2026-10-11T20:00:00',
                                'ended_at': '2026-10-11T20:10:00',
                                'seconds': 600,
                            },
                            'align': {'state': 'completed', 'seconds': 10},
                            'mosaic': {'state': 'completed', 'seconds': 10},
                            'prepare_dolphot': {'state': 'completed', 'seconds': 10},
                            'run_dolphot': {'state': 'completed', 'seconds': 10},
                            'combine_catalogs': {'state': 'completed', 'seconds': 10},
                        },
                    }
                )
            )
            spec = _spec(base_dir=root)
            with patch('manager.st123.campaign_index.list_program_specs') as programs:
                from manager.st123.programs import ProgramSpec

                programs.return_value = (
                    ProgramSpec(
                        program_id='18338',
                        short_name='GO 18338',
                        title='Test',
                        url='http://example.com',
                        output_name='go18338',
                    ),
                )
                with patch(
                    'manager.st123.config.campaign_targets',
                    return_value=[spec],
                ):
                    with patch(
                        'manager.st123.campaign_index.updates_by_target',
                        return_value={},
                    ):
                        stats = ingest_all('18338')
            self.assertEqual(stats['targets'], 1)
            self.assertEqual(Program.objects.count(), 1)
            self.assertEqual(Target.objects.get().n_images, 4)
            self.assertEqual(StageRun.objects.count(), 6)
            rows = list_targets_from_db('18338')
            self.assertIsNotNone(rows)
            self.assertEqual(rows[0]['n_images'], 4)
            self.assertEqual(rows[0]['job_state'], 'completed')
            listed = list_campaign_targets('18338')
            self.assertEqual(listed[0]['name'], 'ngc0157')
            self.assertEqual(listed[0]['n_images'], 4)

    def test_upsert_single_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.pipelinesite').mkdir()
            (root / '.pipelinesite' / 'status.json').write_text(
                json.dumps({'state': 'idle', 'n_images': 2, 'stages': {}})
            )
            Program.objects.create(program_id='18338', short_name='GO 18338', title='T')
            upsert_target_from_spec(_spec(base_dir=root), mast_flags={})
            self.assertEqual(Target.objects.get(name='ngc0157').n_images, 2)
