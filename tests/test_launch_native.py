import tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from bridge.core import digest,write_json
from bridge.native import NativeHOI


class NativeLauncherTests(unittest.TestCase):
    def test_closed_hoi4_launch_validates_runtime_then_starts_worker(self):
        from bridge.launch_native import main
        from native_trial.probe import SIGNATURE
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);runtime=root/'native_trial';runtime.mkdir()
            (runtime/'runtime.dll').write_bytes(b'fixture, never executed')
            write_json(runtime/'manifest.json',{'binaries':{'runtime.dll':digest((runtime/'runtime.dll').read_bytes())}})
            user=root/'user';write_json(user/'dlc_load.json',{'enabled_mods':['mod/hoi4_mow_bridge.mod']})
            transfer=Mock();transfer.pending=None
            with patch('bridge.launch_native.ROOT',root),patch('bridge.launch_native.config',return_value={'hoi4':str(root/'game'),'hoi4_user':str(user)}),patch('bridge.launch_native.running',return_value=False),patch('native_trial.probe.signature',return_value=SIGNATURE),patch('bridge.launch_native.NativeHOI') as native,patch('bridge.launch_native.subprocess.Popen') as process,patch('bridge.transition.AutomaticTransfer',return_value=transfer),patch('bridge.transition._watch') as watch:
                native.return_value.VERSION=NativeHOI.VERSION
                native.return_value.request.return_value={'ok':True,'version':NativeHOI.VERSION,'session_active':True}
                main()
                process.assert_called_once()
                self.assertEqual(process.call_args.kwargs['env']['HOI4_DLL_DEBUG'],'1')
                self.assertIn('--no-mod-sync',process.call_args.args[0])
                watch.assert_called_once()
