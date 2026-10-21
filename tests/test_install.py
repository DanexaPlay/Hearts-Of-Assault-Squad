import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from bridge.install import connect_mod
from bridge.core import BridgeError

class InstallTests(unittest.TestCase):
    def setup_folders(self,root):
        live=root/'runtime/HOI4_MoW_Bridge';old=root/'game/mods/HOI4_MoW_Bridge'
        for p in (live,old):p.mkdir(parents=True);(p/'mod.info').write_text('{mod {name "HOI4_MoW_Bridge"}}')
        (old/'old.txt').write_text('preserve');(live/'live.txt').write_text('editable')
        return {'mow':str(root/'game'),'mow_live_mod':str(live)},live,old
    def test_failed_junction_restores_original_mod(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cfg,live,old=self.setup_folders(root)
            with patch('_winapi.CreateJunction',side_effect=PermissionError('fixture failure')):
                with self.assertRaises(PermissionError):connect_mod(cfg,root)
            self.assertEqual((old/'old.txt').read_text(),'preserve')
            self.assertFalse((old/'live.txt').exists())
    def test_unrelated_mod_is_rejected_before_moving_anything(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cfg,live,old=self.setup_folders(root)
            (old/'mod.info').write_text('{mod {name "Other_Mod"}}')
            with self.assertRaises(BridgeError):connect_mod(cfg,root)
            self.assertEqual((old/'old.txt').read_text(),'preserve')
            self.assertFalse((root/'backups').exists())

if __name__=='__main__':unittest.main()
