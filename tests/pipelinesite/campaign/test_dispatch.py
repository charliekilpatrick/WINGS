from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from manager.st123.config import EXAMPLE_TARGET, NGC1494_TARGET
from manager.st123.inventory import dispatch_availability


class DispatchGateTests(SimpleTestCase):
    def test_blocks_same_target_and_capacity(self):
        live = [{
            'name': 'ngc1494',
            'display_name': 'NGC 1494',
            'pid': 1,
            'message': 'Running Align',
            'started_at': '2026-09-13T17:23:33',
        }]
        same = dispatch_availability(NGC1494_TARGET, jobs=live, max_jobs=2)
        self.assertFalse(same['allowed'])
        self.assertEqual(same['reason'], 'target_running')
        self.assertIn('already running for NGC 1494', same['message'])
        other = dispatch_availability(EXAMPLE_TARGET, jobs=live, max_jobs=1)
        self.assertFalse(other['allowed'])
        self.assertEqual(other['reason'], 'capacity')
        self.assertIn('already running for NGC 1494', other['message'])
        idle = dispatch_availability(NGC1494_TARGET, jobs=[], max_jobs=1)
        self.assertTrue(idle['allowed'])
        self.assertEqual(idle['reason'], 'ok')

    @override_settings(ST123_DISPATCH_LOCK='/tmp/pipelinesite-test-dispatch.lock')
    @patch('manager.st123.runner.dispatch_availability')
    @patch('manager.st123.runner.subprocess.Popen')
    def test_spawn_job_does_not_start_when_blocked(self, popen, gate):
        from manager.st123.runner import spawn_job

        gate.return_value = {
            'allowed': False,
            'reason': 'target_running',
            'message': 'A job is already running for NGC 1494. Wait for it to finish.',
            'running': 1,
            'max_jobs': 1,
            'jobs': [],
        }
        with self.assertRaises(RuntimeError) as ctx:
            spawn_job(['download'], target=NGC1494_TARGET)
        self.assertIn('already running', str(ctx.exception))
        popen.assert_not_called()


class DispatchViewTests(TestCase):
    @patch('manager.st123.inventory.dispatch_availability')
    def test_target_page_disables_dispatch_when_blocked(self, gate):
        gate.return_value = {
            'allowed': False,
            'reason': 'target_running',
            'message': 'A job is already running for NGC 1494. Wait for it to finish.',
            'running': 1,
            'max_jobs': 1,
            'jobs': [],
        }
        page = self.client.get('/manager/targets/ngc1494')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'A job is already running for NGC 1494')
        self.assertContains(page, 'disabled')
        self.assertContains(page, 'data-dispatch-allowed="0"')

    @patch('manager.views.campaign.spawn_job')
    def test_ajax_second_click_is_rejected(self, spawn):
        spawn.side_effect = RuntimeError(
            'A job is already running for NGC 1494. Wait for it to finish.'
        )
        resp = self.client.post(
            '/manager/targets/ngc1494/dispatch',
            {'target': 'ngc1494'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 409)
        self.assertFalse(resp.json()['ok'])
        self.assertIn('already running', resp.json()['error'])
        spawn.assert_called_once()
