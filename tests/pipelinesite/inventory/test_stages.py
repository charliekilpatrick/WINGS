import tempfile
from datetime import datetime, timezone
from pathlib import Path

from django.test import SimpleTestCase

from manager.st123.inventory import (
    build_campaign_status,
    count_science_fits,
    has_science_fits,
    infer_stages,
    remaining_stages,
    _dolphot_run_timing,
    _format_image_size,
    _format_timestamp,
    _science_fits,
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

    def test_empty_raw_after_link_raw_soft_skips_later_stages(self):
        """EXPFLAG-rejected downloads leave an empty reduction/raw directory."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            download = root / 'download' / 'HST' / 'ACS' / 'F814W' / '1'
            download.mkdir(parents=True)
            (download / 'bad_flc.fits').write_bytes(b'simple')
            (root / 'reduction' / 'raw').mkdir(parents=True)
            rows = infer_stages(root)
            by_key = {row['key']: row for row in rows}
            self.assertEqual(by_key['download']['state'], 'completed')
            self.assertEqual(by_key['align']['state'], 'skipped')
            self.assertEqual(by_key['combine_catalogs']['state'], 'skipped')
            self.assertEqual(remaining_stages(rows), [])

    def test_empty_mast_download_is_success_not_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logs = root / 'logs'
            logs.mkdir()
            (logs / 'download_20261009.log').write_text(
                'Found 0 HST imaging observation(s)\n'
                'No matching products for: HST (empty search or all downloads failed)\n'
            )
            stored = {
                'state': 'error',
                'message': 'Download failed with exit 1',
                'stages': {
                    'download': {'state': 'error', 'returncode': 1},
                },
            }
            rows = infer_stages(root, stored)
            by_key = {row['key']: row for row in rows}
            self.assertEqual(by_key['download']['state'], 'completed')
            self.assertEqual(by_key['align']['state'], 'skipped')
            self.assertEqual(remaining_stages(rows), [])


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


class ScienceFitsWalkTests(SimpleTestCase):
    def test_counts_calibrated_products_and_skips_dq(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'download' / 'HST' / 'WFC3' / 'F814W' / '1'
            root.mkdir(parents=True)
            (root / 'frame_flc.fits').write_bytes(b'sci')
            (root / 'frame_c1m.fits').write_bytes(b'dq')
            (root / 'frame_pam.fits').write_bytes(b'pam')
            (root / 'notes.txt').write_text('nope')
            self.assertTrue(has_science_fits(Path(tmp) / 'download'))
            self.assertEqual(count_science_fits(Path(tmp) / 'download'), 1)
            self.assertEqual([p.name for p in _science_fits(Path(tmp) / 'download')], ['frame_flc.fits'])

    def test_quick_infer_matches_empty_mast_remap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logs = root / 'logs'
            logs.mkdir()
            (logs / 'download_20261009.log').write_text(
                'Found 0 HST imaging observation(s)\n'
            )
            stored = {'stages': {'download': {'state': 'error', 'returncode': 1}}}
            rows = infer_stages(root, stored, detailed=False)
            by_key = {row['key']: row for row in rows}
            self.assertEqual(by_key['download']['state'], 'completed')
            self.assertEqual(by_key['align']['state'], 'skipped')

    def test_list_infer_trusts_stored_completed_without_disk_walk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stored = {
                'state': 'idle',
                'n_images': 12,
                'stages': {
                    'download': {'state': 'completed'},
                    'align': {'state': 'completed'},
                    'mosaic': {'state': 'completed'},
                    'prepare_dolphot': {'state': 'completed'},
                    'run_dolphot': {'state': 'completed'},
                    'combine_catalogs': {'state': 'completed'},
                },
            }
            rows = infer_stages(
                root,
                stored,
                detailed=False,
                facts={'has_science': True, 'has_phot': True, 'has_mosaic': True},
            )
            self.assertTrue(all(row['state'] == 'completed' for row in rows))
            self.assertEqual(remaining_stages(rows), [])
            self.assertTrue(all(row['duration'] is None for row in rows))

    def test_infer_uses_stored_timings_without_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stored = {
                'state': 'idle',
                'n_images': 46,
                'stages': {
                    'download': {
                        'state': 'completed',
                        'started_at': '2026-10-11T20:51:04',
                        'ended_at': '2026-10-11T21:02:06',
                        'seconds': 662,
                    },
                    'align': {'state': 'completed', 'seconds': 10},
                    'mosaic': {'state': 'completed', 'seconds': 10},
                    'prepare_dolphot': {'state': 'completed', 'seconds': 10},
                    'run_dolphot': {'state': 'completed', 'seconds': 10},
                    'combine_catalogs': {'state': 'completed', 'seconds': 10},
                },
            }
            rows = infer_stages(root, stored, detailed=False)
            download = {row['key']: row for row in rows}['download']
            self.assertEqual(download['started_at'], '2026-10-11T20:51:04')
            self.assertEqual(download['ended_at'], '2026-10-11T21:02:06')
            self.assertEqual(download['duration'], '11m 02s')


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
