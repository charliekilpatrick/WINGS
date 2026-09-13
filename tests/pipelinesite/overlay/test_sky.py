from django.test import SimpleTestCase

from manager.st123.sky import format_sky, reference_heading, tan_pix_to_world, world_to_pix


class SkyFormatTests(SimpleTestCase):
    def test_tan_and_heading(self):
        ra, dec = tan_pix_to_world(
            2045.392,
            2202.38625,
            [2045.392, 2202.38625],
            [177.66542876963035, 55.35667598884552],
            [[3.70545535332154e-06, 1.04750365511532e-05],
             [1.04750365511532e-05, -3.7054553533215e-06]],
        )
        self.assertAlmostEqual(ra, 177.66542876963035, places=8)
        self.assertAlmostEqual(dec, 55.35667598884552, places=8)
        back = world_to_pix(
            ra,
            dec,
            {
                'crpix': [2045.392, 2202.38625],
                'crval': [177.66542876963035, 55.35667598884552],
                'cd': [
                    [3.70545535332154e-06, 1.04750365511532e-05],
                    [1.04750365511532e-05, -3.7054553533215e-06],
                ],
            },
        )
        self.assertIsNotNone(back)
        self.assertAlmostEqual(back[0], 2045.392, places=4)
        self.assertAlmostEqual(back[1], 2202.38625, places=4)
        self.assertEqual(
            format_sky(177.65595, 55.353589),
            '11:50:37.428 +55:21:12.92',
        )
        self.assertEqual(
            reference_heading({
                'instrument': 'WFC3',
                'detector': 'UVIS',
                'filter': 'F625W',
                'date_obs': '2024-01-25',
            }),
            'Reference image — WFC3/UVIS F625W · 2024-01-25',
        )
