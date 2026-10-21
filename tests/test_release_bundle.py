import unittest
from build_release import validate_paths


class ReleaseBundleTests(unittest.TestCase):
    def test_private_runtime_and_game_files_cannot_enter_bundle(self):
        for name in ('config.json','CONFIG.JSON','runtime/anything.txt','backups/original.txt',
                     'sessions/battle.json','.venv/python','native_trial/hoi4_bridge.dll',
                     'native_trial/hoi4_launcher.exe','map/map.pak','campaign.hoi4',
                     '.env.production','key.pem','profiles/mission.scn'):
            with self.assertRaises(ValueError,msg=name):validate_paths([name])

    def test_paths_are_portable_and_cannot_escape_release_folder(self):
        validate_paths(['Install.cmd','installer.py','assets/mow-ui/mow_main.png',
                        'config.example.json','native_trial/manifest.json','README.md'])
        for name in ('../secret','/absolute/file','C:/absolute/file','a\\..\\secret'):
            with self.assertRaises(ValueError,msg=name):validate_paths([name])
