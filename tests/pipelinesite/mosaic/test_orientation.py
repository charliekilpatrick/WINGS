from pathlib import Path

from django.test import SimpleTestCase

from manager.st123.preview import build_preview
from manager.st123.sky import (
    apply_north_up_east_left,
    north_up_east_left_params,
    read_image_header,
    world_to_pix,
)


class NorthUpEastLeftTests(SimpleTestCase):
    def test_params_put_north_at_plus_y(self):
        # Native CD already nearly North-up / East-left.
        cd = [
            [-1.10363872e-05, -1.28644776e-06],
            [-1.28644776e-06, 1.10363872e-05],
        ]
        delta, flip = north_up_east_left_params(cd)
        self.assertAlmostEqual(delta, -6.648633507554635, places=5)
        self.assertFalse(flip)

    def test_oriented_wcs_is_north_up_east_left(self):
        import numpy as np

        data = np.zeros((100, 80), dtype='uint8')
        data[20:30, 40:50] = 200
        wcs = {
            'crpix': [40.0, 50.0],
            'crval': [10.0, -20.0],
            'cd': [
                [-1.10363872e-05, -1.28644776e-06],
                [-1.28644776e-06, 1.10363872e-05],
            ],
            'nx': 80,
            'ny': 100,
        }
        out, new_wcs = apply_north_up_east_left(data, wcs)
        self.assertEqual(new_wcs['orientation'], 'north_up_east_left')
        cd = new_wcs['cd']
        # +y should increase Dec; +x should decrease RA (East left).
        self.assertGreater(cd[1][1], 0.0)
        self.assertLess(cd[0][0], 0.0)
        self.assertLess(abs(cd[0][1]), abs(cd[0][0]) * 0.05)
        self.assertLess(abs(cd[1][0]), abs(cd[1][1]) * 0.05)

    def test_ngc0247_previews_share_orientation(self):
        root = Path('/data/ckilpatrick/go18440/ngc0247')
        if not root.is_dir():
            self.skipTest('ngc0247 data not present')
        metas = []
        for image_id in ('mosaic-wfc3-f336w-g1r0', 'mosaic-acs-f165lp'):
            meta = build_preview(root, image_id=image_id, force=True)
            self.assertIsNotNone(meta)
            wcs = meta['wcs']
            self.assertEqual(wcs.get('orientation'), 'north_up_east_left')
            cd = wcs['cd']
            self.assertLess(cd[0][0], 0.0)
            self.assertGreater(cd[1][1], 0.0)
            metas.append(meta)
        # A shared sky point projects with North-up geometry on both.
        ra = metas[0]['wcs']['crval'][0]
        dec = metas[0]['wcs']['crval'][1]
        for meta in metas:
            pix = world_to_pix(ra, dec, meta['wcs'])
            self.assertIsNotNone(pix)
