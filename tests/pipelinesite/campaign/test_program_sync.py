import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from manager.st123.config import campaign_targets


_VISIT_HTML = """
<table id="visits2">
  <tr>
    <td class="center-cell">01</td>
    <td>Archived</td>
    <td>NGC7814<br></td>
    <td>WFC3/UVIS<br></td>
    <td>1</td>
    <td>n/a</td>
  </tr>
  <tr>
    <td class="center-cell">02</td>
    <td>Implementation</td>
    <td>ANY<br>NGC0157<br></td>
    <td>WFC3/UVIS<br>ACS/WFC<br></td>
    <td>2</td>
    <td>Not ready</td>
  </tr>
</table>
"""


class ProgramSyncTests(SimpleTestCase):
    def test_parse_visits_and_ready_only_when_observed_and_in_mast(self):
        from manager.st123.program_sync import (
            parse_visit_table,
            pretty_target_name,
            sync_program_targets,
            visit_is_observed,
        )

        self.assertEqual(pretty_target_name('NGC0157'), 'NGC 157')
        self.assertTrue(visit_is_observed('Archived'))
        self.assertFalse(visit_is_observed('Implementation'))
        visits = parse_visit_table(_VISIT_HTML)
        self.assertEqual(len(visits), 2)
        self.assertEqual(visits[0]['targets'], ['NGC 7814'])
        self.assertTrue(visits[0]['observed'])
        self.assertEqual(visits[1]['targets'], ['NGC 157'])
        self.assertFalse(visits[1]['observed'])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / 'campaign_targets.json'
            mast = [
                {
                    'target_name': 'NGC7814',
                    'key': 'NGC7814',
                    'ra': 10.0,
                    'dec': 16.0,
                    'instruments': ('WFC3',),
                    'obs_id': 'iexx01',
                    'public': True,
                },
                {
                    'target_name': 'NGC0157',
                    'key': 'NGC157',
                    'ra': 8.0,
                    'dec': -8.0,
                    'instruments': ('ACS',),
                    'obs_id': 'iexx02',
                    'public': True,
                },
            ]
            result = sync_program_targets(
                program='18338',
                registry_path=registry,
                root=root,
                visit_html=_VISIT_HTML,
                mast_rows=mast,
            )
            self.assertEqual(result['n_ready'], 1)
            self.assertEqual(result['added'], ['ngc7814'])
            ready = [row for row in result['targets'] if row['ready']]
            self.assertEqual(ready[0]['display_name'], 'NGC 7814')
            self.assertTrue((root / 'ngc7814').is_dir())
            with override_settings(ST123_CAMPAIGN_REGISTRY=str(registry)):
                names = [spec.name for spec in campaign_targets()]
            self.assertIn('ngc7814', names)
            self.assertNotIn('ngc157', names)
