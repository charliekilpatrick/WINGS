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
        # ACS stamps are half the L3 footprint, so true full-field aligns stay.
        self.assertIn(('ACS', 'F606W', 'align'), keys)
        self.assertIn(('ACS', 'F814W', 'align'), keys)
        self.assertNotIn(('WFPC2', 'F606W', 'align'), keys)
        self.assertNotIn(('WFPC2', 'F814W', 'align'), keys)
        self.assertEqual(len(mosaics), 6)
        selected = next(row for row in mosaics if row['selected'])
        self.assertEqual(selected['instrument'], 'ACS')
        self.assertEqual(selected['filter'], 'F814W')
        self.assertTrue(selected['option_label'].startswith('ACS F814W'))
        self.assertIn(' · ', selected['option_label'])
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
        # Same-visit align coadds are dropped when they match the mosaic area.
        self.assertTrue(all(row['stage'] == 'mosaic' for row in mosaics))
        self.assertEqual(len(mosaics), 5)
        self.assertTrue(all(' · ' in row['option_label'] for row in mosaics))

    def test_ic1954_dropdown_includes_observation_date(self):
        root = Path('/data/ckilpatrick/HST/ic1954')
        mosaics = discover_mosaic_images(root)
        labels = [row['option_label'] for row in mosaics]
        self.assertTrue(any('WFC3 F275W · 2020-02-14' in label for label in labels))
        self.assertTrue(any('WFC3 F336W · 2020-02-14' in label for label in labels))
        self.assertEqual(len(mosaics), 2)
        self.assertTrue(all(row['stage'] == 'mosaic' for row in mosaics))

    def test_ngc0247_one_coadd_per_visit(self):
        root = Path('/data/ckilpatrick/go18440/ngc0247')
        mosaics = discover_mosaic_images(root)
        labels = [row['option_label'] for row in mosaics]
        self.assertEqual(len(mosaics), 2)
        self.assertEqual(len([label for label in labels if 'F336W' in label]), 1)
        self.assertEqual(len([label for label in labels if 'F165LP' in label]), 1)
        self.assertFalse(any('(full field)' in label for label in labels))
        wfc3 = next(row for row in mosaics if row['filter'] == 'F336W')
        acs = next(row for row in mosaics if row['filter'] == 'F165LP')
        self.assertEqual(wfc3['stage'], 'mosaic')
        self.assertEqual(acs['stage'], 'mosaic')
        # Primary DOLPHOT catalog is the non-empty WFC3 box.
        self.assertTrue(wfc3['is_dolphot_reference'])
        self.assertFalse(acs['is_dolphot_reference'])
        self.assertIn('DOLPHOT reference', wfc3['option_label'])
        self.assertNotIn('DOLPHOT reference', acs['option_label'])
        stamp = discover_reference_image(root)
        self.assertIsNotNone(stamp)
        self.assertIn('wfc3', stamp.name.lower())
        self.assertIn('f336w', stamp.name.lower())


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
