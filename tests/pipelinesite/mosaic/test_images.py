from pathlib import Path

from django.test import SimpleTestCase

from manager.st123.inventory import (
    discover_display_image,
    discover_mosaic_images,
    discover_reference_image,
    resolve_display_image,
)


class MosaicImageTests(SimpleTestCase):
    def test_ngc784_lists_mosaic_filters_only(self):
        root = Path('/data/ckilpatrick/HST/ngc784')
        mosaics = discover_mosaic_images(root)
        keys = {(row['instrument'], row['filter'], row['stage']) for row in mosaics}
        self.assertIn(('ACS', 'F606W', 'mosaic'), keys)
        self.assertIn(('ACS', 'F814W', 'mosaic'), keys)
        self.assertIn(('WFPC2', 'F606W', 'mosaic'), keys)
        self.assertIn(('WFPC2', 'F814W', 'mosaic'), keys)
        self.assertEqual(len(mosaics), 4)
        self.assertTrue(all(row['stage'] == 'mosaic' for row in mosaics))
        selected = next(row for row in mosaics if row['selected'])
        self.assertEqual(selected['instrument'], 'ACS')
        self.assertEqual(selected['filter'], 'F814W')
        self.assertEqual(selected['option_label'], 'ACS F814W (DOLPHOT reference)')
        switched = resolve_display_image(root, 'mosaic-acs-f606w')
        self.assertIsNotNone(switched)
        self.assertIn('f606w', switched.name.lower())

    def test_2026dix_mosaic_dropdown_includes_wfc3_and_wfpc2(self):
        root = Path('/data/ckilpatrick/HST/2026dix')
        mosaics = discover_mosaic_images(root)
        filters = {(row['instrument'], row['filter']) for row in mosaics if row['stage'] == 'mosaic'}
        self.assertIn(('WFC3', 'F625W'), filters)
        self.assertIn(('WFC3', 'F336W'), filters)
        self.assertIn(('WFPC2', 'F814W'), filters)


class DisplayImageTests(SimpleTestCase):
    def test_ngc1494_uses_full_field_not_stamp(self):
        root = Path('/data/ckilpatrick/HST/ngc1494')
        stamp = discover_reference_image(root)
        display = discover_display_image(root)
        self.assertIsNotNone(stamp)
        self.assertIsNotNone(display)
        self.assertNotEqual(display, stamp)
        self.assertIn('l3_ref', str(display))
        from manager.st123.sky import read_image_header
        stamp_hdr = read_image_header(stamp)
        display_hdr = read_image_header(display)
        self.assertGreater(
            (display_hdr['nx'] or 0) * (display_hdr['ny'] or 0),
            4 * (stamp_hdr['nx'] or 0) * (stamp_hdr['ny'] or 0),
        )

    def test_2026dix_keeps_full_dolphot_reference(self):
        root = Path('/data/ckilpatrick/HST/2026dix')
        stamp = discover_reference_image(root)
        display = discover_display_image(root)
        self.assertEqual(stamp, display)
