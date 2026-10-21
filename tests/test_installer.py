import argparse
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import installer


class InstallerTests(unittest.TestCase):
    def test_successful_integration_is_idempotent_and_preserves_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();user=root/'user';user.mkdir()
            raw=b'save_as_binary=yes\nother=1\n';(user/'settings.txt').write_bytes(raw)
            (root/'hoi4_mod').mkdir();(root/'hoi4_mod/descriptor.mod').write_text('name="HOI4 Men of War Bridge"\n')
            cfg={'hoi4_user':str(user),'mow':str(root/'game'),'mow_live_mod':str(root/'runtime/HOI4_MoW_Bridge')}
            with patch.object(installer,'ROOT',root),patch('bridge.install.connect_mod',return_value={'connected':True}):
                installer.integrate(cfg,root/'backup1')
                first=(user/'mod/hoi4_mow_bridge.mod').read_bytes()
                installer.integrate(cfg,root/'backup2')
            self.assertEqual((user/'settings.txt').read_bytes(),raw.replace(b'=yes',b'=no'))
            self.assertEqual((root/'backup1/settings.txt').read_bytes(),raw)
            self.assertEqual((user/'mod/hoi4_mow_bridge.mod').read_bytes(),first)
            self.assertFalse((root/'backup2').exists())

    def test_running_games_or_unsupported_build_stop_before_configuration(self):
        for cause in ('running','build'):
            with tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary)
                with patch.object(installer,'ROOT',root),patch.object(installer,'discover',return_value={}),patch.object(installer,'validate',side_effect=ValueError('unsupported build') if cause=='build' else None),patch('bridge.launch_native.running',return_value=True),patch.object(installer,'run_logged') as execute,patch('sys.argv',['installer.py','--non-interactive']),patch('sys.stdout',new_callable=io.StringIO):
                    with self.assertRaises(ValueError):installer.main()
                    execute.assert_not_called()
                self.assertEqual(list(root.iterdir()),[])
    def test_settings_preserve_other_lines_encoding_and_are_idempotent(self):
        for prefix in (b'', b'\xef\xbb\xbf'):
            raw = prefix + b'language="english"\r\nsave_as_binary=yes\r\nvolume=0.5\r\n'
            result = installer.settings_text(raw)
            self.assertEqual(result, raw.replace(b'save_as_binary=yes', b'save_as_binary=no'))
            self.assertEqual(installer.settings_text(result), result)
        self.assertEqual(installer.settings_text(b'other=1'), b'other=1\nsave_as_binary=no\n')
        for raw in (b'save_as_binary=yes\nsave_as_binary=no\n', b'save_as_binary=unknown\n'):
            with self.assertRaises(ValueError):installer.settings_text(raw)

    def test_failed_integration_restores_original_settings_and_descriptor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve();user = root / 'user';user.mkdir()
            (user / 'settings.txt').write_bytes(b'save_as_binary=yes\nother=1\n')
            (user / 'mod').mkdir()
            descriptor = user / 'mod/hoi4_mow_bridge.mod'
            old = b'name="HOI4 Men of War Bridge (experimental)"\npath="old"\n';descriptor.write_bytes(old)
            (root / 'hoi4_mod').mkdir();(root / 'hoi4_mod/descriptor.mod').write_text('name="HOI4 Men of War Bridge (experimental)"\n')
            cfg = {'hoi4_user':str(user),'mow':str(root / 'game'),'mow_live_mod':str(root / 'runtime/HOI4_MoW_Bridge')}
            backup = root / 'backups/test'
            with patch.object(installer,'ROOT',root),patch('bridge.install.connect_mod',side_effect=PermissionError('fixture denied')):
                with self.assertRaises(PermissionError):installer.integrate(cfg,backup,replace_existing=True)
            self.assertEqual((user / 'settings.txt').read_bytes(), b'save_as_binary=yes\nother=1\n')
            self.assertEqual(descriptor.read_bytes(),old)
            self.assertEqual((backup / 'hoi4_mow_bridge.mod').read_bytes(),old)

    def test_existing_other_installation_needs_explicit_approval_before_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve();user=root/'user';(user/'mod').mkdir(parents=True)
            path=user/'mod/hoi4_mow_bridge.mod';path.write_text('name="HOI4 Men of War Bridge"\npath="old"')
            cfg={'hoi4_user':str(user),'mow':str(root/'game'),'mow_live_mod':str(root/'runtime/HOI4_MoW_Bridge')}
            with patch.object(installer,'ROOT',root),patch('bridge.install.connect_mod') as connect:
                with self.assertRaises(ValueError):installer.integrate(cfg,root/'backup')
                connect.assert_not_called()
            self.assertFalse((root/'backup').exists())

    def test_rollback_refuses_to_overwrite_a_file_changed_by_another_program(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path=root/'settings';path.write_bytes(b'original')
            with self.assertRaisesRegex(ValueError,'откат'):
                with ExitStack() as undo:
                    installer.backed_write(path,b'installer',root/'backup',undo)
                    path.write_bytes(b'user changes')
            self.assertEqual(path.read_bytes(),b'user changes')
            self.assertEqual((root/'backup').read_bytes(),b'original')

    def test_native_ready_requires_every_exact_hash(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);folder=root/'native_trial';folder.mkdir()
            (folder/'manifest.json').write_text(json.dumps({'binaries':{'a.dll':hashlib.sha256(b'verified').hexdigest()}}))
            with patch.object(installer,'ROOT',root):
                self.assertFalse(installer.native_ready())
                (folder/'a.dll').write_bytes(b'wrong');self.assertFalse(installer.native_ready())
                (folder/'a.dll').write_bytes(b'verified');self.assertTrue(installer.native_ready())

    def test_map_preparation_failure_does_not_integrate_games(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();(root/'examples').mkdir();(root/'examples/battle.example.json').write_text('{}')
            cfg={'mow_live_mod':str(root/'runtime/HOI4_MoW_Bridge')}
            with patch.object(installer,'ROOT',root),patch('bridge.launch_native.running',return_value=False),patch.object(installer,'native_ready',return_value=True),patch('bridge.map_bank.supported_maps',return_value=([str(i) for i in range(7)],[])),patch('bridge.map_bank.prepare_bank',side_effect=ValueError('map failed')),patch.object(installer,'integrate') as integrate,patch('Configure.download_native') as download:
                with self.assertRaisesRegex(ValueError,'map failed'):installer.install_worker(cfg,argparse.Namespace(replace_existing=False))
                integrate.assert_not_called();download.assert_not_called()
            self.assertFalse((root/'runtime/installation-complete.json').exists())

    def test_dry_run_never_creates_config_venv_or_downloads(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            with patch.object(installer,'ROOT',root),patch.object(installer,'discover',return_value={'fixture':True}),patch.object(installer,'validate'),patch('bridge.launch_native.running',return_value=False),patch.object(installer,'run_logged') as execute,patch('Configure.download_native') as download,patch('sys.argv',['installer.py','--dry-run','--non-interactive']),patch('sys.stdout',new_callable=io.StringIO):
                installer.main();execute.assert_not_called();download.assert_not_called()
            self.assertEqual(list(root.iterdir()),[])

    @unittest.skipUnless(os.name=='nt','Windows junction test')
    def test_replacing_junction_failure_restores_old_target_without_touching_contents(self):
        import _winapi
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();old=root/'old';old.mkdir();(old/'precious.txt').write_text('unchanged')
            (old/'mod.info').write_text('{name "HOI4_MoW_Bridge"}')
            user=root/'user';user.mkdir();(user/'settings.txt').write_text('save_as_binary=yes\n')
            (root/'hoi4_mod').mkdir();(root/'hoi4_mod/descriptor.mod').write_text('name="HOI4 Men of War Bridge"\n')
            mods=root/'game/mods';mods.mkdir(parents=True);target=mods/'HOI4_MoW_Bridge'
            _winapi.CreateJunction(str(old),str(target))
            cfg={'hoi4_user':str(user),'mow':str(root/'game'),'mow_live_mod':str(root/'runtime/HOI4_MoW_Bridge')}
            try:
                with patch.object(installer,'ROOT',root),patch('bridge.install.connect_mod',side_effect=PermissionError('fixture denied')):
                    with self.assertRaises(PermissionError):installer.integrate(cfg,root/'backup',True)
                self.assertTrue(target.is_junction());self.assertEqual(target.resolve(),old)
                self.assertEqual((old/'precious.txt').read_text(),'unchanged')
                self.assertEqual((user/'settings.txt').read_text(),'save_as_binary=yes\n')
            finally:
                if target.is_junction():target.rmdir()
