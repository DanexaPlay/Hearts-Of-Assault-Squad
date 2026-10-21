import tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from bridge.core import BridgeError,digest
from bridge.mow_launch import start
from bridge.desktop import GameDesktop


class MowLaunchTests(unittest.TestCase):
    def test_only_new_crash_records_report_engine_failure(self):
        from bridge.mow_launch import engine_failure
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);log=root/'game.log'
            crash=b'***************** Exception *****************\nEXCEPTION_ACCESS_VIOLATION'
            previous=crash+b'\nOpening main page\n';log.write_bytes(previous)
            transfer=Mock();transfer.pending={'status':'ready','mow_launch':{'started_at_ns':0,'log_baseline':{'path':str(log),'size':len(previous),'sha256':digest(previous),'head_sha256':digest(previous[:1024])}}}
            with patch('bridge.launch_native.running',return_value=True):
                self.assertIsNone(engine_failure(transfer,{}))
                log.write_bytes(previous+crash)
                self.assertIn('crashed',engine_failure(transfer,{}))
                log.write_bytes(b'Fresh engine log\nOpening main page\n')
                self.assertIsNone(engine_failure(transfer,{}))
                previous=b'x'*2048
                transfer.pending['mow_launch']['log_baseline'].update(size=len(previous),sha256=digest(previous),head_sha256=digest(previous[:1024]))
                log.write_bytes(b'x'*1024+crash+b'y'*4096)
                self.assertIn('crashed',engine_failure(transfer,{}))
                log.write_bytes(b'Fresh engine log\nOpening main page\n')
            with patch('bridge.launch_native.running',return_value=False):
                self.assertIn('closed',engine_failure(transfer,{}))
            transfer.pending['status']='result_ready'
            self.assertIsNone(engine_failure(transfer,{}))

    def transfer(self,folder):
        root=Path(folder);target=root/'HOI4_MoW_Bridge'
        (root/'mowas_2.exe').write_text('test placeholder, never executed')
        mission=target/'resource/map/single/hmb/battle/0.mi'
        mission.parent.mkdir(parents=True);mission.write_text('generated mission')
        transfer=Mock();transfer.pending={'status':'ready','path':str(root),
            'installation':{'target':str(target),'mission_sha256':digest(mission.read_bytes())}}
        transfer.collect_loaded.return_value=None;transfer.collect_final.return_value=None
        return transfer,mission

    def test_manual_restart_proof_rejects_old_engine_old_log_and_multiple_processes(self):
        import os
        from bridge.mow_launch import existing_fresh_engine
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);receipt=root/'.hmb-engine-restart.json';receipt.write_text('installed')
            stamp=receipt.stat().st_mtime_ns
            log=root/'game.log';log.write_text('Opening main page')
            os.utime(log,ns=(stamp+1000,stamp+1000))
            with patch('bridge.launch_native.process_ids',return_value=[123]),patch('bridge.launch_native.process_started_at_ns',return_value=stamp+500) as started:
                proof=existing_fresh_engine(root,log)
                self.assertEqual(proof['process_id'],123)
                self.assertTrue(receipt.exists())  # Proof alone never clears it.
                started.return_value=stamp
                self.assertIsNone(existing_fresh_engine(root,log))
                started.return_value=stamp+2000
                self.assertIsNone(existing_fresh_engine(root,log))
                started.return_value=stamp+500
                log.write_text('Loading resources only')
                self.assertIsNone(existing_fresh_engine(root,log))
            with patch('bridge.launch_native.process_ids',return_value=[123,456]):
                self.assertIsNone(existing_fresh_engine(root,log))

    def test_user_restarted_engine_is_reused_without_repeating_exit(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            transfer,_=self.transfer(folder)
            transfer.pending['installation']['requires_engine_restart']=True
            target=Path(transfer.pending['installation']['target'])
            receipt=target/'.hmb-engine-restart.json';receipt.write_text('installed')
            stamp=receipt.stat().st_mtime_ns
            log=Path(folder)/'game.log';log.write_text('Opening main page')
            os.utime(log,ns=(stamp+1000,stamp+1000))
            with patch('bridge.launch_native.running',side_effect=lambda name:name=='mowas_2.exe'),patch('bridge.launch_native.process_ids',return_value=[123]),patch('bridge.launch_native.process_started_at_ns',return_value=stamp+500),patch('bridge.desktop.GameDesktop') as desktop,patch('bridge.mow_launch.subprocess.Popen') as launch:
                state=start(transfer,{'mow':folder,'mow_log':str(log)},folder)
                self.assertEqual(state['launch_method'],'reuse_running_game')
                self.assertTrue(state['fresh_engine_resources_verified'])
                self.assertEqual(state['manual_restart_verification']['process_id'],123)
                self.assertFalse(receipt.exists())
                launch.assert_not_called();desktop.return_value.close_mow_menu.assert_not_called()
                desktop.return_value.navigate_mission.assert_called_once()

    def test_changed_map_restarts_only_after_menu_proof(self):
        for menu in (True,False):
            with tempfile.TemporaryDirectory() as folder:
                transfer,_=self.transfer(folder);transfer.pending['installation']['requires_engine_restart']=True
                with patch('bridge.launch_native.running',side_effect=[False,True,True,False,False]),patch('bridge.desktop.GameDesktop') as desktop,patch('bridge.mow_launch.subprocess.Popen') as launch,patch('bridge.mow_launch.startup_log_ready',return_value=True):
                    launch.return_value.pid=456
                    desktop.return_value.close_mow_menu.return_value={'kind':'recognized_mow_menu','scene':'mow_main'}
                    if not menu:desktop.return_value.close_mow_menu.side_effect=BridgeError('Still in a battle')
                    if menu:
                        state=start(transfer,{'mow':folder,'mow_log':folder+'/game.log'},folder)
                        self.assertTrue(state['map_cache_restart']);launch.assert_called_once()
                    else:
                        with self.assertRaises(BridgeError):start(transfer,{'mow':folder,'mow_log':folder+'/game.log'},folder)
                        launch.assert_not_called()
                    desktop.return_value.close_mow_menu.assert_called_once()

    def test_closed_game_uses_executable_cwd_but_waits_for_uuid_ack(self):
        with tempfile.TemporaryDirectory() as folder:
            transfer,mission=self.transfer(folder)
            receipt=Path(transfer.pending['installation']['target'])/'.hmb-engine-restart.json'
            receipt.write_text('pending restart')
            with patch('bridge.launch_native.running',return_value=False),patch('bridge.desktop.GameDesktop') as desktop,patch('bridge.mow_launch.subprocess.Popen') as launch,patch('bridge.mow_launch.startup_log_ready',return_value=True):
                launch.return_value.pid=123
                result=start(transfer,{'mow':folder,'mow_log':folder+'/game.log'},folder)
                launch.assert_called_once_with([str(Path(folder)/'mowas_2.exe')],cwd=Path(folder))
                desktop.return_value.navigate_mission.assert_called_once()
                self.assertEqual(result['stage'],'waiting_ack')
                self.assertFalse(result['game_load_verified'])
                self.assertTrue(result['fresh_engine_resources_verified'])
                self.assertFalse(receipt.exists())
                with self.assertRaises(BridgeError):start(transfer,{'mow':folder},folder)
                launch.assert_called_once()

    def test_failed_start_keeps_restart_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            transfer,_=self.transfer(folder)
            receipt=Path(transfer.pending['installation']['target'])/'.hmb-engine-restart.json'
            receipt.write_text('pending restart')
            with patch('bridge.launch_native.running',return_value=False),patch('bridge.desktop.GameDesktop') as desktop,patch('bridge.mow_launch.subprocess.Popen') as launch:
                desktop.return_value.ready_window.return_value=False
                launch.return_value.poll.return_value=2
                launch.return_value.pid=123
                launch.return_value.returncode=2
                with self.assertRaises(BridgeError):start(transfer,{'mow':folder,'mow_log':folder+'/game.log'},folder)
                self.assertTrue(receipt.exists())

    def test_changed_package_and_editor_prevent_launch(self):
        for changed in [True,False]:
            with tempfile.TemporaryDirectory() as folder:
                transfer,mission=self.transfer(folder)
                if changed:mission.write_text('a different battle')
                with patch('bridge.launch_native.running',return_value=True),patch('bridge.mow_launch.subprocess.Popen') as launch:
                    with self.assertRaises(BridgeError):start(transfer,{},folder)
                    launch.assert_not_called()
                    self.assertNotIn('mow_launch',transfer.pending)

    def test_focus_failure_is_recorded_and_not_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            transfer,mission=self.transfer(folder)
            with patch('bridge.launch_native.running',return_value=False),patch('bridge.desktop.GameDesktop') as desktop,patch('bridge.mow_launch.subprocess.Popen') as launch,patch('bridge.mow_launch.startup_log_ready',return_value=True):
                launch.return_value.pid=123
                desktop.return_value.navigate_mission.side_effect=BridgeError('Game lost foreground focus')
                with self.assertRaises(BridgeError):start(transfer,{'mow':folder,'mow_log':folder+'/game.log'},folder)
                desktop.return_value.navigate_mission.assert_called_once()
                self.assertEqual(transfer.pending['mow_launch']['stage'],'stopped')

    def test_splash_is_waited_out_before_menu_navigation(self):
        with tempfile.TemporaryDirectory() as folder:
            transfer,mission=self.transfer(folder)
            with patch('bridge.launch_native.running',return_value=False),patch('bridge.desktop.GameDesktop') as desktop,patch('bridge.mow_launch.subprocess.Popen') as process,patch('bridge.mow_launch.time.sleep') as sleep,patch('bridge.mow_launch.startup_log_ready',return_value=True):
                desktop.return_value.ready_window.side_effect=[False,False,True]
                process.return_value.pid=123
                process.return_value.poll.return_value=None
                start(transfer,{'mow':folder,'mow_log':folder+'/game.log'},folder)
                self.assertEqual(sleep.call_count,2)
                desktop.return_value.navigate_mission.assert_called_once()

    def test_old_log_cannot_make_a_new_engine_appear_ready(self):
        from bridge.mow_launch import startup_log_ready
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'game.log';p.write_bytes(b'Opening main page\n')
            previous=p.read_bytes();stamp=p.stat().st_mtime_ns
            self.assertFalse(startup_log_ready(p,previous,stamp))
            p.write_bytes(previous+b'Loading resources\n')
            self.assertFalse(startup_log_ready(p,previous,stamp))
            p.write_bytes(previous+b'Loading resources\nOpening main page\n')
            self.assertTrue(startup_log_ready(p,previous,stamp))
            p.write_bytes(b'New process\nLoading resources\n')
            self.assertFalse(startup_log_ready(p,previous,stamp))
            p.write_bytes(b'New process\nOpening main page\n')
            self.assertTrue(startup_log_ready(p,previous,stamp))
            self.assertFalse(startup_log_ready(p,b'',p.stat().st_mtime_ns+1))

    def test_space_requires_the_recognized_start_prompt(self):
        for prompt in [True,False]:
            desktop=object.__new__(GameDesktop);desktop.activate=Mock();desktop.click=Mock();desktop.key=Mock()
            desktop.matches=lambda scene:scene=='mow_campaign' or (prompt and scene=='mow_start')
            if prompt:
                desktop.navigate_mission(timeout=0);desktop.key.assert_called_once_with(0x20)
            else:
                with patch('bridge.desktop.time.monotonic',side_effect=[0,0,121]):
                    with self.assertRaises(BridgeError):desktop.navigate_mission(timeout=0)
                desktop.key.assert_not_called()

    def test_manual_start_before_menu_detection_sends_no_input(self):
        desktop=object.__new__(GameDesktop);desktop.activate=Mock();desktop.click=Mock();desktop.key=Mock();desktop.matches=Mock()
        desktop.navigate_mission(acknowledged=lambda:True)
        desktop.click.assert_not_called();desktop.key.assert_not_called();desktop.matches.assert_not_called()

    def test_manual_space_during_loading_sends_no_second_space(self):
        desktop=object.__new__(GameDesktop);desktop.activate=Mock();desktop.click=Mock();desktop.key=Mock()
        desktop.matches=lambda scene:scene=='mow_campaign'
        desktop.navigate_mission(acknowledged=Mock(side_effect=[False,True]))
        desktop.click.assert_called_once_with('mow_campaign',850,251);desktop.key.assert_not_called()

    def test_restart_recovers_native_ack_without_desktop_input(self):
        from bridge.mow_launch import recover_acknowledgment
        with tempfile.TemporaryDirectory() as folder:
            transfer,_=self.transfer(folder)
            transfer.pending.update(mow_launch={'stage':'stopped'},driver_error='old UI failure')
            transfer.collect_final.return_value=None
            def collect():
                transfer.pending['status']='mission_loaded';return {'battle_id':'verified'}
            transfer.collect_loaded.side_effect=collect
            with patch('bridge.desktop.GameDesktop') as desktop:
                self.assertTrue(recover_acknowledgment(transfer))
                desktop.assert_not_called()
            self.assertTrue(transfer.pending['mow_launch']['game_load_verified'])
            self.assertNotIn('driver_error',transfer.pending)

    def test_splash_shape_is_not_a_ready_window(self):
        desktop=object.__new__(GameDesktop);desktop.windows_for=Mock(return_value=[123]);desktop.u=Mock()
        desktop.u.IsIconic.return_value=False
        def rect(width,height):
            def set_rect(handle,p):
                p._obj.left=0;p._obj.top=0;p._obj.right=width;p._obj.bottom=height;return True
            return set_rect
        desktop.u.GetWindowRect.side_effect=rect(683,512)
        self.assertFalse(desktop.ready_window('mow'))
        desktop.u.GetWindowRect.side_effect=rect(1707,1067)
        self.assertTrue(desktop.ready_window('mow'))
        desktop.u.IsIconic.return_value=True
        self.assertTrue(desktop.ready_window('mow'))

    def test_unknown_or_ambiguous_menu_never_clicks(self):
        for answer in [False,True]:
            desktop=object.__new__(GameDesktop);desktop.activate=Mock();desktop.click=Mock()
            desktop.matches=lambda scene:answer
            with self.assertRaises(BridgeError):desktop.navigate_mission(timeout=0)
            desktop.click.assert_not_called()

    def test_game_over_or_ambiguous_screen_does_not_prove_scene_exit(self):
        for answer in [False,True]:
            desktop=object.__new__(GameDesktop);desktop.activate=Mock();desktop.expected=Path('mowas_2.exe')
            desktop.matches=lambda scene:answer
            with self.assertRaises(BridgeError):desktop.confirm_mow_menu()

    def test_explicit_retry_preserves_attempt_and_requires_menu_proof(self):
        from bridge.mow_launch import retry
        with tempfile.TemporaryDirectory() as folder:
            transfer,mission=self.transfer(folder)
            previous={'stage':'stopped','error':'startup shape'};transfer.pending['mow_launch']=previous
            with patch('bridge.launch_native.running',return_value=True),patch('bridge.desktop.GameDesktop') as desktop,patch('bridge.mow_launch.start') as launch:
                desktop.return_value.confirm_mow_menu.side_effect=BridgeError('still in mission')
                with self.assertRaises(BridgeError):retry(transfer,{},folder)
                launch.assert_not_called();self.assertIs(transfer.pending['mow_launch'],previous)
                desktop.return_value.confirm_mow_menu.side_effect=None
                desktop.return_value.confirm_mow_menu.return_value={'kind':'recognized_mow_menu','scene':'mow_main'}
                retry(transfer,{},folder);launch.assert_called_once()
                self.assertEqual(transfer.pending['mow_launch_attempts'][0]['error'],'startup shape')
                self.assertEqual(transfer.pending['mow_launch_attempts'][0]['retry_preflight']['scene'],'mow_main')

    def test_interrupted_start_can_be_explicitly_retried_when_game_is_closed(self):
        from bridge.mow_launch import retry
        with tempfile.TemporaryDirectory() as folder:
            transfer,_=self.transfer(folder);transfer.pending['mow_launch']={'stage':'starting'}
            with patch('bridge.launch_native.running',return_value=False),patch('bridge.mow_launch.start') as launch:
                retry(transfer,{},folder)
                launch.assert_called_once()
            self.assertEqual(transfer.pending['mow_launch_attempts'][0]['retry_preflight']['kind'],'mow_process_closed')

    def test_menu_timeout_stops_before_mission_click(self):
        desktop=object.__new__(GameDesktop);desktop.activate=Mock();desktop.click=Mock()
        desktop.matches=lambda scene:scene=='mow_single'
        desktop.wait=Mock(side_effect=BridgeError('Menu did not change'))
        with self.assertRaises(BridgeError):desktop.navigate_mission(timeout=0)
        desktop.click.assert_called_once_with('mow_single',850,281)
