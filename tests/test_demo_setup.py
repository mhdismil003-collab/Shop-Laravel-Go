"""Regression checks for lost .env recovery and stale PowerShell overrides."""
import base64
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import shop_demo


class DemoSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / '.env.example').write_text('API_PORT=8080\nAPP_KEY=\nJWT_SIGNING_KEY=\nADMIN_PASSWORD=\n')
        self.root_patch = patch.object(shop_demo, 'ROOT', self.root)
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.temporary.cleanup()

    def test_missing_env_recovers_existing_container_credentials(self):
        key = base64.b64encode(bytes(range(32))).decode()
        def existing(service):
            return {'api': {'ADMIN_EMAIL': 'existing@shop.local', 'ADMIN_PASSWORD': 'Existing1!',
                            'APP_KEY': 'base64:' + key, 'JWT_SIGNING_KEY': key},
                    'postgres': {'POSTGRES_DB': 'old_shop', 'POSTGRES_USER': 'old_user', 'POSTGRES_PASSWORD': 'Old-db1!'},
                    'warehouse-db': {'POSTGRES_PASSWORD': 'Old-warehouse1!'}}[service]
        with patch.object(shop_demo, 'container_settings', side_effect=existing), patch.object(shop_demo.getpass, 'getpass') as prompt:
            values = shop_demo.initialize()
        prompt.assert_not_called()
        saved = shop_demo.read_settings()
        self.assertEqual(saved['POSTGRES_PASSWORD'], 'Old-db1!')
        self.assertEqual(saved['POSTGRES_DB'], 'old_shop')
        self.assertEqual(saved['JWT_SIGNING_KEY'], key)
        self.assertEqual(saved['ADMIN_PASSWORD'], values['ADMIN_PASSWORD'])

    def test_new_install_creates_valid_distinct_keys_and_preserves_special_password(self):
        password = "Demo1!'$\\=quoted"
        with patch.object(shop_demo, 'container_settings', return_value={}), patch.object(shop_demo.getpass, 'getpass', return_value=password):
            shop_demo.initialize()
        saved = shop_demo.read_settings()
        self.assertEqual(saved['ADMIN_PASSWORD'], password)
        self.assertTrue(shop_demo.valid_key(saved['APP_KEY'], True))
        self.assertTrue(shop_demo.valid_key(saved['JWT_SIGNING_KEY']))
        self.assertNotEqual(saved['APP_KEY'][7:], saved['JWT_SIGNING_KEY'])

    def test_repeated_setup_keeps_valid_configuration(self):
        with patch.object(shop_demo, 'container_settings', return_value={}), patch.object(shop_demo.getpass, 'getpass', return_value='Demo1!Password'):
            first = shop_demo.initialize()
            second = shop_demo.initialize()
        self.assertEqual(first, second)

    def test_child_compose_does_not_inherit_stale_project_secrets(self):
        with patch.dict(os.environ, {'JWT_SIGNING_KEY': 'stale', 'ADMIN_PASSWORD': 'wrong'}), patch.object(shop_demo.subprocess, 'run') as run:
            run.return_value.returncode = 0
            shop_demo.docker('config', '--quiet')
            self.assertNotIn('JWT_SIGNING_KEY', run.call_args.kwargs['env'])
            self.assertNotIn('ADMIN_PASSWORD', run.call_args.kwargs['env'])
            self.assertEqual(os.environ['JWT_SIGNING_KEY'], 'stale')


if __name__ == '__main__':
    unittest.main()
