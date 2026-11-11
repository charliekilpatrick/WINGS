import unittest

from manager.st123.sn_host import (
    apply_hosts_to_targets,
    literature_host,
    parse_ned_cone_galaxies,
    pretty_galaxy_name,
    resolve_sn_host,
)


class SnHostTests(unittest.TestCase):
    def test_literature_override_2017hta(self):
        hit = literature_host('SN 2017HTA')
        self.assertIsNotNone(hit)
        self.assertEqual(hit['host'], 'UGCA 81')
        self.assertIn('purdue', hit['source'])

    def test_pretty_galaxy_name_strips_leading_zeros(self):
        self.assertEqual(pretty_galaxy_name('UGCA 081'), 'UGCA 81')
        self.assertEqual(pretty_galaxy_name('NGC0337'), 'NGC 337')

    def test_ned_cone_prefers_named_galaxy(self):
        html = """
        <pre>
        1   WISEA J033947.00+664300.0   03h39m47.0s +66d43m00s IrS
        2   UGCA 081                    03h40m07.9s +66d42m46s G  1496 0.004990 S1L 9.91 1.999
        3   SDSS J033950.00+664310.0    03h39m50.0s +66d43m10s G  0.1
        </pre>
        """
        rows = parse_ned_cone_galaxies(html)
        self.assertTrue(rows)
        self.assertEqual(rows[0]['host'], 'UGCA 81')
        self.assertAlmostEqual(rows[0]['separation_arcmin'], 1.999)

    def test_resolve_uses_literature_before_tns(self):
        def boom(_name):
            raise AssertionError('TNS should not be consulted')

        hit = resolve_sn_host(
            'sn2017hta',
            ra=54.95,
            dec=66.72,
            query_tns=boom,
            use_ned=False,
            use_glade=False,
        )
        self.assertEqual(hit['host'], 'UGCA 81')
        self.assertEqual(hit['source'], 'purdue-bright-sne')

    def test_resolve_falls_back_to_ned_cone(self):
        hit = resolve_sn_host(
            'SN 9999zzz',
            ra=1.0,
            dec=2.0,
            query_tns=lambda _n: '',
            query_ned=lambda ra, dec, radius_arcmin=5.0: {
                'host': 'NGC 1234',
                'source': 'ned-cone',
                'separation_arcmin': 0.4,
            },
            use_glade=False,
        )
        self.assertEqual(hit['host'], 'NGC 1234')
        self.assertEqual(hit['source'], 'ned-cone')

    def test_apply_hosts_fills_missing_sn_rows(self):
        targets = [
            {'name': 'sn2017hta', 'display_name': 'SN 2017HTA', 'host': '', 'ra': 54.95, 'dec': 66.72},
            {'name': 'ngc3003', 'display_name': 'NGC 3003', 'host': 'NGC 3003', 'ra': 1.0, 'dec': 2.0},
        ]
        updates = apply_hosts_to_targets(targets)
        self.assertEqual(updates['sn2017hta'], 'UGCA 81')
        self.assertEqual(targets[0]['host'], 'UGCA 81')
        self.assertNotIn('ngc3003', updates)
