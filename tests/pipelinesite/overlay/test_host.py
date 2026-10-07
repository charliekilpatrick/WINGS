import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from manager.st123.host_distance import (
    classify_ned_method,
    format_distance,
    lookup_host_distance,
    select_ned_distance,
    shared_host_distance,
)


class HostDistanceTests(SimpleTestCase):
    def test_format_and_ned_cache_roundtrip(self):
        self.assertEqual(
            format_distance({
                'distance_mpc': 14.824,
                'distance_err_mpc': 1.553,
                'catalog': 'GLADE+',
            }),
            '14.8 ± 1.6 Mpc (GLADE+)',
        )
        self.assertEqual(
            format_distance({
                'distance_mpc': 3.34,
                'distance_err_mpc': 0.05,
                'catalog': 'NED',
                'method': 'Cepheids',
            }),
            '3.3 ± 0.1 Mpc (NED Cepheids)',
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / '.pipelinesite' / 'host_distance.json'
            cache.parent.mkdir(parents=True)
            cache.write_text(
                '{'
                '"key": {"host": "NGC 247", "ra": 11.78564, "dec": -20.7604},'
                '"distance_mpc": 3.34, "distance_err_mpc": 0.05,'
                '"catalog": "NED", "method": "Cepheids"'
                '}'
            )
            with override_settings(ST123_OUTPUT_ROOT=tmp):
                record = lookup_host_distance(
                    host='NGC 247',
                    ra=11.78564,
                    dec=-20.7604,
                    base_dir=root,
                    query_ned=lambda host: self.fail('should use NED cache'),
                )
            self.assertEqual(record['catalog'], 'NED')
            self.assertEqual(record['method'], 'Cepheids')
            self.assertEqual(record['distance_mpc'], 3.34)

    def test_method_ladder_prefers_cepheids(self):
        self.assertEqual(classify_ned_method('Cepheids')[1], 'Cepheids')
        self.assertEqual(classify_ned_method('TRGB')[1], 'TRGB')
        self.assertEqual(classify_ned_method('SNIa')[1], 'SN Ia')
        self.assertEqual(classify_ned_method('Tully-Fisher')[1], 'Tully-Fisher')
        self.assertEqual(classify_ned_method('Tully est')[1], 'Tully-Fisher')
        self.assertEqual(classify_ned_method('SBF')[1], 'SBF')
        chosen = select_ned_distance(
            [
                {'method': 'Tully-Fisher', 'distance_mpc': 8.0, 'dist_mod': 29.5, 'dist_mod_err': 0.2},
                {'method': 'TRGB', 'distance_mpc': 3.7, 'dist_mod': 27.8, 'dist_mod_err': 0.1},
                {'method': 'Cepheids', 'distance_mpc': 3.27, 'dist_mod': 27.57, 'dist_mod_err': 0.12},
                {'method': 'Cepheids', 'distance_mpc': 3.38, 'dist_mod': 27.64, 'dist_mod_err': 0.04},
                {'method': 'SNIa', 'distance_mpc': 4.1, 'dist_mod': 28.0, 'dist_mod_err': 0.15},
            ],
            host='NGC 247',
        )
        self.assertEqual(chosen['method'], 'Cepheids')
        self.assertAlmostEqual(chosen['distance_mpc'], 3.325, places=3)
        self.assertEqual(chosen['n_measurements'], 2)

    def test_glade_cache_is_replaced_by_ned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / '.pipelinesite' / 'host_distance.json'
            cache.parent.mkdir(parents=True)
            cache.write_text(
                '{'
                '"key": {"host": "NGC 247", "ra": 11.78564, "dec": -20.7604},'
                '"distance_mpc": 4.14, "distance_err_mpc": 1.2, "catalog": "GLADE+"'
                '}'
            )
            with override_settings(ST123_OUTPUT_ROOT=tmp):
                record = lookup_host_distance(
                    host='NGC 247',
                    ra=11.78564,
                    dec=-20.7604,
                    base_dir=root,
                    query_ned=lambda host: [
                        {
                            'method': 'Cepheids',
                            'distance_mpc': 3.31,
                            'dist_mod': 27.6,
                            'dist_mod_err': 0.09,
                        }
                    ],
                )
            self.assertEqual(record['catalog'], 'NED')
            self.assertEqual(record['method'], 'Cepheids')
            self.assertAlmostEqual(record['distance_mpc'], 3.31)
            stored = cache.read_text()
            self.assertIn('NED', stored)
            self.assertIn('Cepheids', stored)

    def test_shared_host_cache_covers_prime_and_parallel(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            prime = out / 'ngc0157'
            parallel = out / 'ngc0157par'
            with override_settings(ST123_OUTPUT_ROOT=str(out)):
                first = lookup_host_distance(
                    host='NGC 157',
                    ra=8.6941,
                    dec=-8.3963,
                    base_dir=prime,
                    query_ned=lambda host: [
                        {
                            'method': 'Tully-Fisher',
                            'distance_mpc': 12.8,
                            'dist_mod': 30.5,
                            'dist_mod_err': 0.1,
                        }
                    ],
                )
                shared = shared_host_distance('NGC 157')
                second = lookup_host_distance(
                    host='NGC 157',
                    ra=8.7674,
                    dec=-8.4674,
                    base_dir=parallel,
                    remote=False,
                    query_ned=lambda host: self.fail('parallel should reuse host cache'),
                )
            self.assertEqual(first['method'], 'Tully-Fisher')
            self.assertEqual(shared['distance_mpc'], first['distance_mpc'])
            self.assertEqual(second['distance_mpc'], first['distance_mpc'])
