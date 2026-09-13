import tempfile
from datetime import datetime, timezone
from pathlib import Path

from django.test import SimpleTestCase

from manager.st123.inventory import (
    infer_stages,
    remaining_stages,
    _dolphot_run_timing,
    _format_image_size,
    _format_timestamp,
)


class StageInferenceTests(SimpleTestCase):
    def test_remaining_includes_missing_hdf5(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            download = root / 'download' / 'HST' / 'WFC3' / 'F625W' / '1'
            download.mkdir(parents=True)
            (download / 'frame_flc.fits').write_bytes(b'simple')
            rows = infer_stages(root)
            by_key = {row['key']: row for row in rows}
            self.assertEqual(by_key['download']['state'], 'completed')
            self.assertEqual(by_key['combine_catalogs']['state'], 'pending')
            self.assertIn('combine_catalogs', remaining_stages(rows))


class DolphotRuntimeTests(SimpleTestCase):
    def test_elapsed_from_dolphot_err(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / 'dolphot' / 'hst_0_0'
            run.mkdir(parents=True)
            (run / 'dolphot.param').write_text('img0_file = ref\n')
            (run / 'dolphot.err').write_text('ELAPSED_SEC=693.21\n')
            (run / 'hst_0_0.phot').write_text('0 0 1 1 1 20 0.01 0 0 0.1 1\n')
            _start, _end, seconds = _dolphot_run_timing(root)
            self.assertAlmostEqual(seconds, 693.21)
            rows = infer_stages(root)
            by_key = {row['key']: row for row in rows}
            self.assertEqual(by_key['run_dolphot']['state'], 'completed')
            self.assertEqual(by_key['run_dolphot']['duration'], '11m 33s')


class TimestampFormatTests(SimpleTestCase):
    def test_iso_seconds_only(self):
        self.assertEqual(
            _format_timestamp(datetime(2026, 8, 4, 17, 50, 19, 453737, tzinfo=timezone.utc)),
            '2026-08-04T17:50:19',
        )
        self.assertEqual(_format_image_size([(2051, 4096), (2051, 4096)]), '2 × 4096 × 2051')
        self.assertEqual(
            _format_image_size([(800, 800), (800, 800), (800, 800), (800, 800)]),
            '4 × 800 × 800',
        )
