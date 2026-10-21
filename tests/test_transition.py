import copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from bridge.transition import AutomaticTransfer,request_fields,select_requested_combat,install_generated_mod,worker_lock
from bridge.core import BridgeError

class TransitionTests(unittest.TestCase):
    def test_invalid_terminal_result_is_reported_but_initial_save_keeps_waiting(self):
        from bridge.core import write_json,read_json
        for ending in ('initial','finished_flag','terminal_thread'):
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);progress=root/'profile/game_progress.set';save=progress.parent/'save/autosave1';save.mkdir(parents=True)
                auto=AutomaticTransfer({'hoi4_user':str(root),'mow_progress':str(progress)},root/'sessions')
                auto.request('HMB_REQUEST: country=GER seq=1');session=Path(auto.pending['path'])
                auto.pending.update(status='mission_loaded',requested_at_ns=0)
                write_json(session/'battle.json',{'id':'a'*32});write_json(session/'roster.json',[])
                (save/'mission.scn').write_text('hmb_'+'a'*32);(save/'game.scn').write_text('snapshot')
                with patch('bridge.transition.parse_result',side_effect=BridgeError('casualty mismatch')),patch('bridge.transition.saved_variable',return_value=int(ending=='finished_flag')),patch('bridge.gem.terminal_autosave_winner',side_effect=BridgeError('not finished') if ending=='initial' else None):
                    self.assertIsNone(auto.collect_final())
                    if ending=='initial':self.assertIsNone(auto.collect_final())
                    else:
                        with self.assertRaisesRegex(BridgeError,'Finished tactical result could not be verified'):auto.collect_final()
                        self.assertEqual(read_json(session/'result-read-error.json')['error'],'casualty mismatch')
                self.assertEqual(auto.pending['status'],'mission_loaded')
                self.assertFalse((session/'result.json').exists())

    def test_busy_request_keeps_first_session_and_does_not_export_second(self):
        from bridge.transition import TransitionBusy
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);auto=AutomaticTransfer({'hoi4_user':str(root)},root/'sessions')
            first=auto.request('HMB_REQUEST: country=GER seq=1');auto.pending['status']='mission_loaded';auto._record()
            old=(auto.active_file.read_bytes(),(Path(first['path'])/'transition.json').read_bytes())
            with self.assertRaises(TransitionBusy):auto.request('HMB_REQUEST: country=GER seq=2')
            self.assertIs(auto.pending,first)
            self.assertEqual(old,(auto.active_file.read_bytes(),(Path(first['path'])/'transition.json').read_bytes()))
            self.assertEqual(len([p for p in auto.root.iterdir() if p.is_dir()]),1)

    def test_worker_rejects_second_request_without_stopping_first_result_monitor(self):
        from unittest.mock import Mock
        from bridge.transition import _watch,TransitionBusy
        transfer=Mock();transfer.pending={'status':'mission_loaded','path':'first'}
        transfer.request.side_effect=TransitionBusy('A tactical transition is already active')
        transfer.find_fresh_snapshot.return_value=None;transfer.collect_loaded.return_value=None;transfer.collect_final.return_value=None
        cfg={'hoi4_user':'example'}
        with patch('bridge.requests.RequestWatcher') as watcher,patch('bridge.transition.AutomaticTransfer',return_value=transfer),patch('bridge.native.NativeHOI') as native,patch('bridge.status.SilentStatus') as status,patch('bridge.transition.time.sleep',side_effect=StopIteration):
            watcher.return_value.poll.return_value=['HMB_REQUEST: country=GER seq=2']
            with self.assertRaises(StopIteration):_watch(cfg,Path('example'),native=True)
            native.return_value.capture.assert_not_called()
            transfer.collect_final.assert_called_once();transfer.collect_loaded.assert_called_once()
            self.assertEqual(status.return_value.update.call_args.args[0],'rejected')

    def test_geometry_change_requires_restart_but_a_new_roster_does_not(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';target=root/'HOI4_MoW_Bridge'
            rel=Path('resource/map/single/hmb/battle')
            for p in (source,target):
                (p/rel).mkdir(parents=True);(p/'mod.info').write_text('mod')
                (p/rel/'0.mi').write_text('same roster');(p/rel/'map.ply').write_text('summer')
            (source/rel/'0.mi').write_text('new roster')
            self.assertFalse(install_generated_mod(source,target,root/'first')['requires_engine_restart'])
            (source/rel/'map.ply').write_text('winter')
            report=install_generated_mod(source,target,root/'second')
            self.assertTrue(report['requires_engine_restart'])
            self.assertEqual(report['changed_map_resources'],[(rel/'map.ply').as_posix()])

    def test_entity_definition_changes_require_one_cold_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';target=root/'HOI4_MoW_Bridge'
            for p in (source,target):
                (p/'resource/map/single/hmb/battle').mkdir(parents=True)
                (p/'mod.info').write_text('mod')
                (p/'resource/map/single/hmb/battle/0.mi').write_text('mission')
            rel=Path('resource/entity/service/hmb_prep_vehicle_wall/wall.def')
            asset=source/rel;asset.parent.mkdir(parents=True);asset.write_text('construction collider')
            report=install_generated_mod(source,target,root/'first')
            self.assertTrue(report['requires_engine_restart'])
            self.assertEqual(report['changed_entity_resources'],[rel.as_posix()])
            # A second install cannot acknowledge a running engine's VFS.
            self.assertTrue(install_generated_mod(source,target,root/'second')['requires_engine_restart'])
            (target/'.hmb-engine-restart.json').unlink()
            self.assertFalse(install_generated_mod(source,target,root/'warm')['requires_engine_restart'])
            asset.write_text('changed collider')
            self.assertTrue(install_generated_mod(source,target,root/'updated')['requires_engine_restart'])

    def test_changed_difficulty_requires_restart_only_when_rules_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';target=root/'HOI4_MoW_Bridge'
            for p in (source,target):
                (p/'resource/map/single/hmb/battle').mkdir(parents=True)
                (p/'mod.info').write_text('mod')
                (p/'resource/map/single/hmb/battle/0.mi').write_text('mission')
            rules=source/'resource/set/difficulty/normal.dl';rules.parent.mkdir(parents=True);rules.write_text('normal')
            first=install_generated_mod(source,target,root/'first')
            self.assertTrue(first['requires_engine_restart'])
            self.assertEqual(first['changed_difficulty_resources'],['resource/set/difficulty/normal.dl'])
            self.assertTrue(install_generated_mod(source,target,root/'second')['requires_engine_restart'])
            # Only the loader's fresh-process acknowledgement clears this.
            (target/'.hmb-engine-restart.json').unlink()
            self.assertFalse(install_generated_mod(source,target,root/'acknowledged')['requires_engine_restart'])
            rules.write_text('heroic')
            self.assertTrue(install_generated_mod(source,target,root/'third')['requires_engine_restart'])

    def test_manual_mission_ack_requires_its_own_uuid_and_stable_files(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);profile=root/'profile';save=profile/'save/autosave1';save.mkdir(parents=True)
            auto=AutomaticTransfer({'hoi4_user':str(root),'mow_progress':str(profile/'game_progress.set')},root/'sessions')
            auto.request('HMB_REQUEST: country=GER seq=1')
            session=Path(auto.pending['path']);bid='a'*32
            (session/'battle.json').write_text(json.dumps({'id':bid}));(session/'roster.json').write_text('[]')
            native=save/'mission.scn'
            native.write_text('hmb_'+'b'*32);(save/'game.scn').write_text('state')
            auto.pending.update(status='ready',requested_at_ns=0)
            with patch('bridge.transition.saved_variable',side_effect=lambda text,name:1 if name=='hmb_initial_snapshot' else 0),patch('bridge.transition.analyze_saved_actors',return_value={}) as audit,patch('bridge.transition.archive_result_evidence',side_effect=lambda r,s:r):
                self.assertIsNone(auto.collect_loaded());self.assertIsNone(auto.collect_loaded());audit.assert_not_called()
                native.write_text('hmb_'+bid)
                self.assertIsNone(auto.collect_loaded())
                self.assertEqual(auto.collect_loaded()['battle_id'],bid)
                self.assertEqual(auto.pending['status'],'mission_loaded');audit.assert_called_once()

    def test_ui_failure_keeps_worker_listening_for_manual_mission(self):
        from unittest.mock import Mock
        from bridge.transition import _watch
        with tempfile.TemporaryDirectory() as folder:
            transfer=Mock();transfer.pending={'status':'ready','path':folder}
            transfer.find_fresh_snapshot.return_value=None
            transfer.collect_loaded.return_value=None;transfer.collect_final.return_value=None
            cfg={'hoi4_user':folder,'mow_auto_load':True}
            with patch('bridge.requests.RequestWatcher') as watcher,patch('bridge.transition.AutomaticTransfer',return_value=transfer),patch('bridge.native.NativeHOI'),patch('bridge.mow_launch.recover_acknowledgment',return_value=False),patch('bridge.mow_launch.start',side_effect=BridgeError('Overlay obscured prompt')),patch('bridge.transition.time.sleep',side_effect=StopIteration):
                watcher.return_value.poll.return_value=[]
                with self.assertRaises(StopIteration):_watch(cfg,Path(folder),install=True,native=True)
            self.assertEqual(transfer.pending['mow_launch']['stage'],'manual_wait')
            transfer.collect_loaded.assert_called_once();transfer.collect_final.assert_called_once()

    def test_open_mow_requires_positive_menu_exit_before_release(self):
        from unittest.mock import Mock
        from bridge.transition import release_completed
        for menu in [True,False]:
            with tempfile.TemporaryDirectory() as folder:
                transfer=Mock();transfer.pending={'status':'result_ready','strategic_result_applied':True,'path':folder}
                with patch('bridge.launch_native.running',return_value=True),patch('bridge.desktop.GameDesktop') as desktop:
                    if menu:desktop.return_value.confirm_mow_menu.return_value={'kind':'recognized_mow_menu','scene':'mow_main'}
                    else:desktop.return_value.confirm_mow_menu.side_effect=BridgeError('Still in a mission')
                    self.assertFalse(release_completed(transfer,{},allow_menu=False))
                    desktop.assert_not_called();transfer.release.assert_not_called()
                    if menu:
                        self.assertTrue(release_completed(transfer,{},allow_menu=True))
                        transfer.release.assert_called_once()
                        self.assertEqual(transfer.pending['mission_exit_verification']['scene'],'mow_main')
                    else:
                        with self.assertRaises(BridgeError):release_completed(transfer,{},allow_menu=True)
                        transfer.release.assert_not_called()
                        self.assertNotIn('mission_exit_verification',transfer.pending)

    def test_native_worker_resumes_archived_unattempted_result_after_restart(self):
        from unittest.mock import Mock
        from bridge.transition import _watch
        transfer=Mock();transfer.pending={'status':'result_ready','path':'example'}
        transfer.find_fresh_snapshot.return_value=None
        transfer.collect_loaded.return_value=None;transfer.collect_final.return_value=None
        cfg={'hoi4_user':'example'}
        with patch('bridge.requests.RequestWatcher') as watcher,patch('bridge.transition.AutomaticTransfer',return_value=transfer),patch('bridge.native.NativeHOI'),patch('bridge.transition.complete_native_return') as apply,patch('bridge.transition.time.sleep',side_effect=StopIteration):
            watcher.return_value.poll.return_value=[]
            with self.assertRaises(StopIteration):_watch(cfg,Path('example'),native=True)
            apply.assert_called_once_with(transfer,cfg)

    def test_worker_lock_prevents_two_services_and_releases_on_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            with worker_lock(folder):
                with self.assertRaises(BridgeError):
                    with worker_lock(folder):pass
            with worker_lock(folder):pass
    def setUp(self):
        self.campaign={'player_country':'GER','combats':[{'combat_id':'1:62','province':20,'attacker':[{'country':'GER'}],'defender':[{'country':'SOV'}]}]}
    def test_explicit_battle_and_ambiguity_do_not_export_wrong_battle(self):
        extra=copy.deepcopy(self.campaign['combats'][0]);extra.update(combat_id='2:62',province=30)
        self.campaign['combats'].append(extra)
        with self.assertRaises(BridgeError):select_requested_combat(self.campaign,{'country':'GER'})
        self.assertEqual(select_requested_combat(self.campaign,{'province':'30'})['combat_id'],'2:62')
        with self.assertRaises(BridgeError):select_requested_combat(self.campaign,{'country':'SOV','combat':'1:62'})
    def test_request_rejects_unexpanded_loc_and_injected_values(self):
        self.assertEqual(request_fields('log: HMB_REQUEST: country=GER seq=2'),{'country':'GER','seq':'2'})
        for line in ('HMB_REQUEST: country=[ROOT.GetTag]','HMB_REQUEST: combat=../x','HMB_REQUEST: province=0','HMB_REQUEST: seq=1 seq=2'):
            with self.assertRaises(BridgeError):request_fields(line)
    def test_snapshot_must_contain_exact_request_sequence(self):
        self.campaign['countries']={'GER':{'hmb_request_seq':2}}
        self.assertEqual(select_requested_combat(self.campaign,{'country':'GER','seq':'2'})['combat_id'],'1:62')
        for seq in ('1','3'):
            with self.assertRaises(BridgeError):select_requested_combat(self.campaign,{'country':'GER','seq':seq})
    def test_active_mission_survives_service_restart_and_prevents_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cfg={'hoi4_user':str(root)}
            auto=AutomaticTransfer(cfg,root/'sessions');auto.request('HMB_REQUEST: country=GER seq=1')
            auto.pending.update(status='ready',installation={'target':'dedicated'});auto._record()
            resumed=AutomaticTransfer(cfg,root/'sessions')
            self.assertEqual(resumed.pending['status'],'ready')
            with self.assertRaises(BridgeError):resumed.request('HMB_REQUEST: country=GER seq=2')
            with self.assertRaises(BridgeError):resumed.release()
            resumed.pending['status']='result_ready';resumed._record();resumed.release()
            self.assertFalse(resumed.active_file.exists())
            self.assertIsNotNone(resumed.request('HMB_REQUEST: country=GER seq=2'))
    def test_result_collection_waits_for_stable_matching_autosave(self):
        import json,time
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);profile=root/'profile';save=profile/'save/autosave1';save.mkdir(parents=True)
            cfg={'hoi4_user':str(root),'mow_progress':str(profile/'game_progress.set')}
            auto=AutomaticTransfer(cfg,root/'sessions');auto.request('HMB_REQUEST: country=GER seq=1')
            session=Path(auto.pending['path']);bid='a'*32
            (session/'battle.json').write_text(json.dumps({'id':bid}));(session/'roster.json').write_text('[]')
            (save/'mission.scn').write_text('hmb_'+bid);(save/'game.scn').write_text('state')
            auto.pending['status']='ready';auto.pending['requested_at_ns']=0;auto._record()
            result={'winner':'attacker'}
            with patch('bridge.transition.parse_result',return_value=result) as parser,patch('bridge.transition.archive_result_evidence',side_effect=lambda r,s:r):
                self.assertIsNone(auto.collect_final());parser.assert_not_called()
                self.assertEqual(auto.collect_final(),result)
                self.assertEqual(auto.pending['status'],'result_ready')
                self.assertIsNone(auto.collect_final());self.assertEqual(parser.call_count,1)
    def test_existing_save_is_not_exported_and_new_save_must_stabilize(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);saves=root/'save games';saves.mkdir()
            old=saves/'old.hoi4';old.write_text('old')
            auto=AutomaticTransfer({'hoi4_user':str(root)},root/'sessions')
            auto.request('HMB_REQUEST: country=GER seq=1')
            self.assertIsNone(auto.find_fresh_snapshot())
            new=saves/'new.hoi4';new.write_text('new')
            self.assertIsNone(auto.find_fresh_snapshot())
            self.assertEqual(auto.find_fresh_snapshot(),new.resolve())
            self.assertIsNone(auto.request('HMB_REQUEST: country=GER seq=1'))
            with self.assertRaises(BridgeError):auto.request('HMB_REQUEST: country=GER seq=2')
    def test_install_preserves_unrelated_files_and_backs_up_old_mission(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';target=root/'HOI4_MoW_Bridge';session=root/'session'
            for p in (source,target): (p/'resource/map/single/hmb/battle').mkdir(parents=True)
            (source/'mod.info').write_text('mod')
            mission=Path('resource/map/single/hmb/battle/0.mi')
            (source/mission).write_text('new');(target/mission).write_text('old');(target/'unrelated.txt').write_text('keep')
            report=install_generated_mod(source,target,session)
            self.assertEqual((target/mission).read_text(),'new')
            self.assertEqual((session/'install-backup'/mission).read_text(),'old')
            self.assertEqual((target/'unrelated.txt').read_text(),'keep')
            self.assertFalse(report['game_load_verified'])
    def test_write_failure_rolls_back_every_previously_changed_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';target=root/'HOI4_MoW_Bridge';source.mkdir();target.mkdir()
            (source/'mod.info').write_text('new meta');(target/'mod.info').write_text('old meta')
            mission=source/'resource/map/single/hmb/battle/0.mi';mission.parent.mkdir(parents=True);mission.write_text('mission')
            (source/'z-last.txt').write_text('last')
            original=Path.replace
            def fail_last(path,dest):
                if Path(dest).name=='z-last.txt':raise PermissionError('fixture denial')
                return original(path,dest)
            with patch.object(Path,'replace',fail_last):
                with self.assertRaises(PermissionError):install_generated_mod(source,target,root/'session')
            self.assertEqual((target/'mod.info').read_text(),'old meta')
            self.assertFalse((target/'z-last.txt').exists())

if __name__=='__main__':unittest.main()
