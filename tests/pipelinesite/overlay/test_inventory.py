from django.test import SimpleTestCase

from manager.st123.inventory import format_obs_datetime


class ObsDatetimeTests(SimpleTestCase):
    def test_combines_date_and_time(self):
        self.assertEqual(
            format_obs_datetime('2020-01-05', '00:45:23'),
            '2020-01-05T00:45:23',
        )
        self.assertEqual(
            format_obs_datetime('2024-01-25T03:24:09.123'),
            '2024-01-25T03:24:09',
        )
        self.assertEqual(format_obs_datetime('2024-01-25'), '2024-01-25')
        self.assertIsNone(format_obs_datetime(None))
