import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from manager.st123.config import TargetSpec
from manager.st123.mast_updates import (
    assign_observations,
    check_program_updates,
    local_image_tokens,
    obs_on_disk,
)


def _spec(name='ngc0157', ra=8.6, dec=-8.4, base_dir=None):
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
        program_id='18338',
        field_role='prime',
    )


class MastUpdateLogicTests(TestCase):
    def test_assigns_nearest_sky_and_detects_new_obs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prime = _spec(base_dir=root / 'ngc0157')
            other = _spec(name='ngc7814', ra=10.7, dec=16.1, base_dir=root / 'ngc7814')
            mast = [
                {
                    'target_name': 'NGC157',
                    'key': 'NGC157',
                    'ra': 8.61,
                    'dec': -8.41,
                    'obs_id': 'iexx01',
                },
                {
                    'target_name': 'NGC7814',
                    'key': 'NGC7814',
                    'ra': 10.68,
                    'dec': 16.14,
                    'obs_id': 'iexx99',
                },
            ]
            assigned = assign_observations([prime, other], mast)
            self.assertEqual([row['obs_id'] for row in assigned['ngc0157']], ['iexx01'])
            self.assertEqual([row['obs_id'] for row in assigned['ngc7814']], ['iexx99'])

            with override_settings(ST123_OUTPUT_ROOT=tmp):
                first = check_program_updates(
                    '18338',
                    mast_rows=mast[:1],
                    targets=[prime],
                )
                self.assertEqual(first['n_new_targets'], 0)
                second = check_program_updates(
                    '18338',
                    mast_rows=mast,
                    targets=[prime],
                )
                self.assertEqual(second['n_new_targets'], 0)
                flagged = check_program_updates(
                    '18338',
                    mast_rows=[
                        mast[0],
                        {
                            'target_name': 'NGC157',
                            'key': 'NGC157',
                            'ra': 8.60,
                            'dec': -8.40,
                            'obs_id': 'iexx02',
                        },
                    ],
                    targets=[prime],
                )
                self.assertEqual(flagged['n_new_targets'], 1)
                row = flagged['targets'][0]
                self.assertTrue(row['new_available'])
                self.assertIn('IEXX02', row['pending_obs_ids'])

                download = prime.base_dir / 'download' / 'HST' / 'WFC3' / 'F814W' / 'iexx02'
                download.mkdir(parents=True)
                (download / 'iexx02_flc.fits').write_bytes(b'')
                self.assertTrue(obs_on_disk('iexx02', local_image_tokens(prime.base_dir)))
                cleared = check_program_updates(
                    '18338',
                    mast_rows=[
                        mast[0],
                        {
                            'target_name': 'NGC157',
                            'key': 'NGC157',
                            'ra': 8.60,
                            'dec': -8.40,
                            'obs_id': 'iexx02',
                        },
                    ],
                    targets=[prime],
                )
                self.assertEqual(cleared['n_new_targets'], 0)

    def test_run_campaign_pipeline_is_serial(self):
        specs = [_spec(name='a'), _spec(name='b', ra=1.0, dec=1.0)]
        seen = []
        with patch('manager.st123.runner.run_stages', side_effect=lambda keys, target=None: seen.append(target.name)):
            with patch(
                'manager.management.commands.run_campaign_pipeline.campaign_targets',
                return_value=specs,
            ):
                call_command('run_campaign_pipeline', program=['18338'], verbosity=0)
        self.assertEqual(seen, ['a', 'b'])


class MastFlagPageTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user('viewer', password='secret')
        self.client.force_login(user)

    def test_program_pages_show_new_data_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'go18338' / '.pipelinesite'
            dest.mkdir(parents=True)
            (dest / 'mast_updates.json').write_text(
                json.dumps(
                    {
                        'program_id': '18338',
                        'checked_at': '2026-10-09T12:00:00+00:00',
                        'n_new_targets': 1,
                        'targets': [
                            {
                                'name': 'ngc0157',
                                'display_name': 'NGC 157',
                                'new_available': True,
                                'n_pending': 1,
                                'pending_obs_ids': ['IEXXNEW'],
                                'seen_obs_ids': ['IEXXNEW'],
                            }
                        ],
                    }
                )
            )
            with override_settings(ST123_OUTPUT_ROOT=tmp):
                home = self.client.get('/')
                self.assertContains(home, 'with new MAST data')
                page = self.client.get('/programs/18338')
                self.assertContains(page, 'New MAST data are available')
                self.assertContains(page, 'new data available')
                target = self.client.get('/manager/targets/ngc0157')
                self.assertContains(target, 'New MAST data are available')
                self.assertContains(target, 'Process new data')
