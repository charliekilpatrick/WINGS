from django.test import SimpleTestCase

from manager.st123.status_tags import derive_status_tag, status_label_for_row


class StatusTagTests(SimpleTestCase):
    def test_empty_mast_when_complete_with_zero_images(self):
        tag = derive_status_tag(
            job_state='completed',
            n_images=0,
            new_data=False,
            remaining=[],
        )
        self.assertEqual(tag, 'empty_mast')
        self.assertEqual(status_label_for_row(tag), 'no data yet (0/0)')

    def test_new_data_beats_complete(self):
        tag = derive_status_tag(
            job_state='completed',
            n_images=4,
            new_data=True,
            remaining=[],
        )
        self.assertEqual(tag, 'new_data')

    def test_running_from_stages(self):
        tag = derive_status_tag(
            job_state='pending',
            n_images=2,
            new_data=False,
            remaining=['mosaic'],
            stages=[{'state': 'running'}],
        )
        self.assertEqual(tag, 'running')
