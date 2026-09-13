from pathlib import Path

from django.test import SimpleTestCase

from manager.st123.st123api import display_filter, filter_name


class St123FilterTests(SimpleTestCase):
    def test_acs_clear_wheel_uses_st123_get_filter(self):
        root = Path('/data/ckilpatrick/HST/ngc784/download')
        frames = sorted(root.rglob('j8yy12ptq_flc.fits')) + sorted(root.rglob('j8yy12pqq_flc.fits'))
        self.assertEqual(len(frames), 2)
        self.assertEqual(display_filter(filter_name(frames[0])), 'F606W')
        self.assertEqual(display_filter(filter_name(frames[1])), 'F814W')
