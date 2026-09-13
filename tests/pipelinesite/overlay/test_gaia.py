import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from manager.st123.gaia import format_wcs_quality, load_gaia_overlay


class GaiaOverlayTests(SimpleTestCase):
    def test_on_image_and_used_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gaia_dir = root / 'reduction' / 'gaia'
            l3_dir = root / 'reduction' / 'jhat' / 'l3_ref'
            gaia_dir.mkdir(parents=True)
            l3_dir.mkdir(parents=True)
            (gaia_dir / 'gaiadr3_radec.txt').write_text(
                '# ra dec\n'
                '177.66542877 55.35667599\n'
                '180.0 0.0\n'
            )
            (l3_dir / 'coadd.phot.txt').write_text(
                'ra dec mag x y dmag\n'
                '177.66543 55.35668 -3.0 100 100 0.05\n'
            )
            wcs = {
                'crpix': [2045.392, 2202.38625],
                'crval': [177.66542876963035, 55.35667598884552],
                'cd': [
                    [3.70545535332154e-06, 1.04750365511532e-05],
                    [1.04750365511532e-05, -3.7054553533215e-06],
                ],
                'nx': 4091,
                'ny': 4405,
            }
            overlay = load_gaia_overlay(root, wcs)
            self.assertEqual(overlay['n_on_image'], 1)
            self.assertEqual(overlay['n_used'], 1)
            self.assertTrue(overlay['stars'][0]['used'])
            self.assertIsNotNone(overlay['rms_mas'])
            self.assertIn('RMS =', format_wcs_quality(overlay))
