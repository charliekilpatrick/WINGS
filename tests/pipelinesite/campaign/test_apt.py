from django.test import SimpleTestCase, override_settings

from manager.st123.apt import output_slug, parse_equatorial
from manager.st123.config import campaign_targets, find_target


class AptCatalogTests(SimpleTestCase):
    def test_output_slug_keeps_zeros_and_marks_parallels(self):
        self.assertEqual(output_slug('NGC0157'), 'ngc0157')
        self.assertEqual(output_slug('NGC0157', parallel=True), 'ngc0157par')
        self.assertEqual(output_slug('NGC1291-1'), 'ngc1291-1')
        self.assertEqual(output_slug('IC1954'), 'ic1954')

    def test_parse_equatorial(self):
        ra, dec = parse_equatorial('00 34 46.5840 -08 23 46.68')
        self.assertAlmostEqual(ra, 8.6941, places=3)
        self.assertAlmostEqual(dec, -8.3963, places=3)

    def test_campaign_catalogs_come_from_phase2(self):
        go18338 = campaign_targets('18338')
        names = [spec.name for spec in go18338]
        self.assertEqual(len(go18338), 190)
        self.assertIn('ngc0157', names)
        self.assertIn('ngc0157par', names)
        self.assertIn('ngc7814', names)
        self.assertNotIn('ngc1494', names)
        prime = find_target('ngc0157')
        parallel = find_target('ngc0157par')
        self.assertEqual(prime.field_role, 'prime')
        self.assertEqual(parallel.field_role, 'parallel')
        self.assertEqual(prime.host, parallel.host)
        self.assertEqual(str(prime.base_dir), '/data/ckilpatrick/go18338/ngc0157')
        self.assertEqual(str(parallel.base_dir), '/data/ckilpatrick/go18338/ngc0157par')
        self.assertGreater(
            abs(prime.ra - parallel.ra) + abs(prime.dec - parallel.dec),
            0.01,
        )
        self.assertEqual(prime.instruments, ('ACS', 'WFC3', 'WFPC2'))
        self.assertEqual(parallel.instruments, ('ACS', 'WFC3', 'WFPC2'))

        go18440 = campaign_targets('18440')
        names_18440 = [spec.name for spec in go18440]
        self.assertEqual(len(go18440), 43)
        self.assertIn('ic1954', names_18440)
        self.assertIn('ngc0247', names_18440)
        self.assertIn('ngc1291-1', names_18440)
        self.assertTrue(all(spec.field_role == 'prime' for spec in go18440))
        ic1954 = find_target('ic1954')
        self.assertEqual(str(ic1954.base_dir), '/data/ckilpatrick/go18440/ic1954')
        self.assertIn('F336W', ic1954.filters)

    @override_settings(ST123_OUTPUT_ROOT='/tmp/pipelinesite-output')
    def test_output_root_override_rebased_target_dirs(self):
        spec = find_target('ngc0157')
        self.assertEqual(str(spec.base_dir), '/tmp/pipelinesite-output/go18338/ngc0157')
