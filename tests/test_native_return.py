import tempfile
import unittest
from pathlib import Path
from bridge.core import digest, BridgeError
from bridge.native_return import publish


class NativeReturnTests(unittest.TestCase):
    def test_engine_hp_truncates_ratio_before_multiplication(self):
        from unittest.mock import patch
        from bridge.save_import import vanilla_strength_from_manpower
        division={'template':{'components':[{'type':'infantry'}]},'required_manpower':9300,'manpower':7050}
        with patch('bridge.formations.unit_definitions',return_value={'infantry':{'max_strength':225.2}}):
            self.assertEqual(vanilla_strength_from_manpower(division),170.71511)

    def test_publish_copies_verified_file_and_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'prepared'/'return.hoi4';source.parent.mkdir()
            source.write_bytes(b'verified campaign');saves=root/'saves';saves.mkdir()
            report={'prepared':{'path':str(source),'output_sha256':digest(source.read_bytes())}}
            publish(report,saves)
            self.assertEqual((saves/source.name).read_bytes(),source.read_bytes())
            publish(report,saves)
            (saves/source.name).write_bytes(b'another campaign')
            with self.assertRaises(BridgeError):publish(report,saves)
            self.assertEqual((saves/source.name).read_bytes(),b'another campaign')
