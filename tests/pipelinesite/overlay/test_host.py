import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from manager.st123.host_distance import format_distance, lookup_host_distance


class HostDistanceTests(SimpleTestCase):
    def test_format_and_cache_roundtrip(self):
        self.assertEqual(
            format_distance({
                'distance_mpc': 14.824,
                'distance_err_mpc': 1.553,
                'catalog': 'GLADE+',
            }),
            '14.8 ± 1.6 Mpc (GLADE+)',
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / '.pipelinesite' / 'host_distance.json'
            cache.parent.mkdir(parents=True)
            cache.write_text(
                '{'
                '"key": {"host": "NGC 3913", "ra": 177.65595, "dec": 55.35359},'
                '"distance_mpc": 14.8, "distance_err_mpc": 1.6, "catalog": "GLADE+"'
                '}'
            )
            record = lookup_host_distance(
                host='NGC 3913',
                ra=177.65595,
                dec=55.35359,
                base_dir=root,
            )
            self.assertEqual(record['catalog'], 'GLADE+')
            self.assertEqual(record['distance_mpc'], 14.8)
