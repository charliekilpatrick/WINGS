import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from manager.st123.inventory import summarize_catalog

from tests.pipelinesite.helpers import write_phot


class CatalogCutTests(SimpleTestCase):
    def test_quality_cuts_count_before_and_after(self):
        with tempfile.TemporaryDirectory() as tmp:
            phot = Path(tmp) / 'hst_0_0.phot'
            write_phot(
                phot,
                [
                    (10, 10, 20, 0.01, 0.1, 1),
                    (11, 11, 20, 0.8, 0.1, 1),
                    (12, 12, 20, 0.01, 2.0, 1),
                    (13, 13, 20, 0.01, 0.1, 2),
                ],
            )
            summary = summarize_catalog(
                phot,
                cuts={'types': (1,), 'sharp_max': 0.3, 'crowd_max': 0.5, 'snr_min': None},
            )
            self.assertEqual(summary['n_before'], 4)
            self.assertEqual(summary['n_after'], 1)
            self.assertEqual(summary['rejected']['sharp'], 1)
            self.assertEqual(summary['rejected']['crowd'], 1)
            self.assertEqual(summary['rejected']['type'], 1)
