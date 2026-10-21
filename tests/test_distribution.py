import argparse
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import zipfile
import Configure


class DistributionTests(unittest.TestCase):
    def test_configuration_is_local_and_never_replaces_existing_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'config.example.json').write_text('{}')
            for folder, executable in [('hoi4', 'hoi4.exe'), ('mow', 'mowas_2.exe')]:
                (root / folder).mkdir()
                (root / folder / executable).write_bytes(b'fixture')
            progress = root / 'game_progress.set'
            progress.write_text('{}')
            args = argparse.Namespace(hoi4=str(root / 'hoi4'), mow=str(root / 'mow'),
                                      hoi4_user=str(root / 'hoi4-user'), mow_progress=str(progress))
            with patch.object(Configure, 'ROOT', root):
                cfg = Configure.configuration(args)
                self.assertEqual(Path(cfg['mow_live_mod']), root / 'runtime/HOI4_MoW_Bridge')
                saved = (root / 'config.json').read_bytes()
                with self.assertRaises(FileExistsError):Configure.configuration(args)
                self.assertEqual((root / 'config.json').read_bytes(), saved)

    def test_download_validates_archive_and_each_binary_before_writing(self):
        for bad in ('none', 'archive', 'binary'):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                folder = root / 'native_trial';folder.mkdir()
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, 'w') as archive:
                    archive.writestr('release/hoi4_launcher.exe', b'launcher')
                    archive.writestr('release/hoi4_bridge.dll', b'bridge')
                data = buffer.getvalue()
                manifest = {'archive_sha256':hashlib.sha256(data).hexdigest(), 'binaries':{
                    'hoi4_launcher.exe':hashlib.sha256(b'launcher').hexdigest(),
                    'hoi4_bridge.dll':hashlib.sha256(b'bridge').hexdigest()}}
                if bad == 'archive':manifest['archive_sha256'] = '0' * 64
                if bad == 'binary':manifest['binaries']['hoi4_bridge.dll'] = '0' * 64
                (folder / 'manifest.json').write_text(json.dumps(manifest))
                with patch.object(Configure, 'ROOT', root),patch('Configure.urllib.request.urlopen',return_value=io.BytesIO(data)):
                    if bad == 'none':
                        Configure.download_native()
                        self.assertEqual((folder / 'hoi4_bridge.dll').read_bytes(), b'bridge')
                    else:
                        with self.assertRaises(ValueError):Configure.download_native()
                        self.assertFalse((folder / 'hoi4_launcher.exe').exists())
                        self.assertFalse((folder / 'hoi4_bridge.dll').exists())

    def test_register_refuses_to_replace_another_bridge_descriptor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'hoi4_mod').mkdir()
            (root / 'hoi4_mod/descriptor.mod').write_text('name="fixture"\n')
            cfg = {'hoi4_user':str(root / 'user')}
            with patch.object(Configure, 'ROOT', root):
                Configure.register_hoi(cfg)
                descriptor = root / 'user/mod/hoi4_mow_bridge.mod'
                self.assertIn((root / 'hoi4_mod').as_posix(), descriptor.read_text())
                descriptor.write_text('another installation')
                with self.assertRaises(ValueError):Configure.register_hoi(cfg)
                self.assertEqual(descriptor.read_text(), 'another installation')
