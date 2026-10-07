import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from manager.st123.config import find_target


class AuthPageTests(TestCase):
    def test_anonymous_users_are_sent_to_login(self):
        home = self.client.get('/')
        self.assertEqual(home.status_code, 302)
        self.assertIn('/accounts/login/', home['Location'])
        login = self.client.get('/accounts/login/')
        self.assertEqual(login.status_code, 200)
        self.assertContains(login, 'Sign in')
        self.assertNotContains(login, 'GO 18338')

    def test_regular_user_cannot_open_admin(self):
        user = get_user_model().objects.create_user('viewer', password='secret')
        self.client.force_login(user)
        home = self.client.get('/')
        self.assertEqual(home.status_code, 200)
        self.assertNotContains(home, '>Admin<')
        denied = self.client.get('/admin-console/')
        self.assertEqual(denied.status_code, 403)

    def test_admin_can_add_users_and_see_tab(self):
        admin = get_user_model().objects.create_user(
            'boss', password='secret', is_staff=True, is_superuser=True
        )
        self.client.force_login(admin)
        home = self.client.get('/')
        self.assertContains(home, '>Admin<')
        page = self.client.get('/admin-console/')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Add user')
        self.assertContains(page, 'Add target')
        created = self.client.post(
            '/admin-console/',
            {
                'action': 'add_user',
                'username': 'newuser',
                'email': 'new@example.com',
                'password': 'other-secret',
                'is_admin': '',
            },
        )
        self.assertEqual(created.status_code, 302)
        user = get_user_model().objects.get(username='newuser')
        self.assertFalse(user.is_staff)
        self.assertTrue(user.check_password('other-secret'))

    def test_admin_can_add_a_target(self):
        admin = get_user_model().objects.create_user(
            'boss', password='secret', is_staff=True, is_superuser=True
        )
        self.client.force_login(admin)
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(
                ST123_OUTPUT_ROOT=tmp,
                ST123_CAMPAIGN_REGISTRY='',
            ):
                resp = self.client.post(
                    '/admin-console/',
                    {
                        'action': 'add_target',
                        'program_id': '18338',
                        'name': 'ngc9999',
                        'display_name': 'NGC 9999',
                        'host': 'NGC 9999',
                        'field_role': 'prime',
                        'ra': '10.5',
                        'dec': '-8.25',
                        'radius_arcmin': '5',
                        'notes': 'test target',
                    },
                )
                self.assertEqual(resp.status_code, 302)
                spec = find_target('ngc9999')
                self.assertIsNotNone(spec)
                self.assertEqual(spec.host, 'NGC 9999')
                self.assertEqual(spec.program_id, '18338')
                self.assertTrue(str(spec.base_dir).endswith('go18338/ngc9999'))
                self.assertTrue((Path(tmp) / 'go18338' / '.pipelinesite' / 'campaign_targets.json').is_file())
