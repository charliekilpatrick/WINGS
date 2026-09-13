import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from manager.st123.inventory import catalog_sources
from manager.st123.photometry import (
    build_filter_plan,
    flux_snr,
    row_ab_mags,
    three_sigma_limit,
    vega_to_ab_offset,
)


class PhotometryParseTests(SimpleTestCase):
    def test_combined_vega_to_ab(self):
        self.assertAlmostEqual(vega_to_ab_offset('WFPC2', 'F606W'), 0.100)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            columns = root / 'run.phot.columns'
            phot = root / 'run.phot'
            columns.write_text(
                '1. Extension\n'
                '2. Chip\n'
                '3. Object X position\n'
                '4. Object Y position\n'
                '5. Chi for fit\n'
                '6. Signal-to-noise\n'
                '7. Object sharpness\n'
                '8. Object roundness\n'
                '9. Direction of major axis\n'
                '10. Crowding\n'
                '11. Object type\n'
                '12. Pass Detected\n'
                '13. Total counts, WFPC2_F606W\n'
                '17. Instrumental VEGAMAG magnitude, WFPC2_F606W\n'
                '19. Magnitude uncertainty, WFPC2_F606W\n'
            )
            cols = ['0'] * 20
            cols[2] = '10.0'
            cols[3] = '12.0'
            cols[4] = '1.1'
            cols[5] = '30'
            cols[6] = '0.01'
            cols[7] = '0.02'
            cols[9] = '0.1'
            cols[10] = '1'
            cols[16] = '24.234'
            cols[18] = '0.168'
            phot.write_text(' '.join(cols) + '\n')
            plan = build_filter_plan(columns)
            mags = row_ab_mags(cols, plan)
            self.assertEqual(len(mags), 1)
            self.assertEqual(mags[0]['name'], 'WFPC2 F606W')
            self.assertAlmostEqual(mags[0]['mag'], 24.334)
            self.assertAlmostEqual(mags[0]['magerr'], 0.168)
            self.assertFalse(mags[0]['is_limit'])
            sources = catalog_sources(phot)
            self.assertEqual(sources[0]['mags'][0]['system'], 'AB')
            self.assertAlmostEqual(sources[0]['mags'][0]['mag'], 24.334)


class PhotometryLimitTests(SimpleTestCase):
    def test_three_sigma_limit_from_large_error(self):
        self.assertAlmostEqual(flux_snr(1.653), 1.0857362047581294 / 1.653, places=5)
        limit = three_sigma_limit(27.135, 1.653)
        self.assertAlmostEqual(limit, 25.486, places=2)
        row = {
            'mag': 27.135,
            'magerr': 1.653,
            'snr': flux_snr(1.653),
            'is_limit': True,
            'limit_mag': limit,
        }
        self.assertTrue(row['is_limit'])
        self.assertLess(row['limit_mag'], 27.135)
