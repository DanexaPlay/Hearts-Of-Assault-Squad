import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from bridge.core import Ledger,write_json,read_json,digest,BridgeError
from bridge.transition import AutomaticTransfer
from bridge.return_recovery import abandon_partial

class ReturnRecoveryTests(unittest.TestCase):
    def test_strength_receipt_recovery_never_replays_losses_and_timeout_is_not_retried(self):
        import json
        from unittest.mock import Mock
        from bridge.return_recovery import finalize_completed_partial
        for mode in ('success','changed','timeout'):
            with tempfile.TemporaryDirectory() as folder:
                transfer,session,backup=self.fixture(Path(folder))
                plan={'campaign_id':'c','battle_id':'a'*32,'before':{'hour':100}}
                state={'campaign_id':'c','hour':100,'units':{'1:51':{'hp':90}}}
                write_json(session/'live-plan.json',plan)
                write_json(session/'live-return.json',{'stage':'failed_requires_inspection','error':'Strength/organization verification failed','partial_state':state})
                client=Mock();client.client.health.return_value={'paused':True,'game_hour':100}
                client.inspect.return_value=state if mode!='changed' else {**state,'hour':101}
                def request(route,body,**kwargs):
                    if 'finalize_verified' in body:
                        if mode=='timeout':raise BridgeError('timeout')
                        return {'result':json.dumps(state)}
                    return {'result':'{}'}
                client.client.request.side_effect=request
                with patch('bridge.return_recovery.LiveHOI',return_value=client),patch('bridge.return_recovery.preserve_current',return_value=backup) as preserve:
                    if mode=='success':
                        report=finalize_completed_partial(transfer,{})
                        self.assertFalse(report['additional_losses_applied'])
                        self.assertTrue(transfer.pending['strategic_result_applied'])
                        self.assertEqual(read_json(session/'live-return.json')['stage'],'verified')
                    else:
                        with self.assertRaises(BridgeError):finalize_completed_partial(transfer,{})
                        self.assertFalse(transfer.pending.get('strategic_result_applied',False))
                        if mode=='changed':preserve.assert_not_called()
                        if mode=='timeout':
                            with self.assertRaises(BridgeError):finalize_completed_partial(transfer,{})
                    client.apply.assert_not_called();client.cancel.assert_not_called()
                    calls=[c.args[1] for c in client.client.request.call_args_list]
                    self.assertEqual(sum('finalize_verified' in c for c in calls),0 if mode=='changed' else 1)
                    self.assertFalse(any('HMB_LIVE.apply(' in c for c in calls))

    def fixture(self,root):
        transfer=AutomaticTransfer({'hoi4_user':str(root)},root/'sessions')
        transfer.request('HMB_REQUEST: country=GER seq=1');session=Path(transfer.pending['path'])
        transfer.pending.update(status='result_ready',native_return_stage='applying_direct');transfer._record()
        write_json(session/'live-return.json',{'stage':'failed_requires_inspection'})
        write_json(session/'live-plan.json',{'campaign_id':'c','battle_id':'a'*32})
        ledger=Ledger(session/'ledger.sqlite')
        with ledger.db:ledger.db.execute('INSERT INTO battles VALUES(?,?,?,NULL)',('a'*32,'{}','live_failed'))
        ledger.db.close()
        backup=session/'recovery/verified/current-campaign.hoi4';backup.parent.mkdir(parents=True);backup.write_bytes(b'current campaign')
        return transfer,session,{'stage':'backup_verified','campaign_id':'c','backup_path':str(backup),'backup_sha256':digest(backup.read_bytes())}

    def test_explicit_keep_retires_only_partial_result_without_engine_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            transfer,session,backup=self.fixture(Path(folder))
            with patch('bridge.return_recovery.LiveHOI') as native:
                result=abandon_partial(transfer,backup);native.assert_not_called()
            self.assertFalse(result['additional_losses_applied'])
            self.assertIsNone(transfer.pending);self.assertFalse(transfer.active_file.exists())
            saved=read_json(session/'transition.json')
            self.assertEqual(saved['status'],'return_abandoned')
            self.assertNotIn('strategic_result_applied',saved)
            ledger=Ledger(session/'ledger.sqlite')
            self.assertEqual(ledger.db.execute('SELECT status FROM battles').fetchone()[0],'abandoned_partial');ledger.db.close()
            self.assertTrue(Path(backup['backup_path']).exists())
            self.assertEqual(read_json(session/'live-return.json')['stage'],'failed_requires_inspection')
            with self.assertRaises(BridgeError):abandon_partial(transfer,backup)

    def test_resolution_resumes_after_disk_error_without_replaying_result(self):
        for failure in ('record','remove_pointer'):
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);transfer,session,backup=self.fixture(root)
                original_unlink=Path.unlink
                def unlink(path,*args,**kwargs):
                    if path==transfer.active_file:raise OSError('simulated interruption')
                    return original_unlink(path,*args,**kwargs)
                if failure=='record':
                    with patch.object(transfer,'_record',side_effect=OSError('simulated interruption')):
                        with self.assertRaises(OSError):abandon_partial(transfer,backup)
                else:
                    with patch.object(Path,'unlink',unlink):
                        with self.assertRaises(OSError):abandon_partial(transfer,backup)
                restarted=AutomaticTransfer({'hoi4_user':str(root)},root/'sessions')
                with patch('bridge.return_recovery.LiveHOI') as native:
                    result=abandon_partial(restarted,backup);native.assert_not_called()
                self.assertFalse(result['additional_losses_applied'])
                self.assertFalse(restarted.active_file.exists())

    def test_restored_original_snapshot_is_recognized_without_relaxing_gameplay_match(self):
        import copy
        from bridge.return_recovery import classify_loaded_campaign
        before={'campaign_id':'c','hour':100,'gs':1000,'flags':{},'combats':{'1:62':{'addr':2000,'province':3134}},
            'units':{'1:51':{'addr':3000,'province':11183,'equipment':{'8:70':{'variant':4000,'addr':5000,'amount':100000}}}}}
        plan={'campaign_id':'c','battle_id':'a'*32,'before':before}
        restored=copy.deepcopy(before);restored['gs']=11000;restored['combats']['1:62']['addr']=12000
        restored['units']['1:51'].update(addr=13000)
        restored['units']['1:51']['equipment']['8:70'].update(addr=14000,variant=15000)
        self.assertEqual(classify_loaded_campaign(plan,restored),'original_pre_return_snapshot_restored')
        for change in ('hour','gear','combat','campaign','applied'):
            state=copy.deepcopy(restored)
            if change=='hour':state['hour']+=1
            if change=='gear':state['units']['1:51']['equipment']['8:70']['amount']-=1
            if change=='combat':state['combats']={}
            if change=='campaign':state['campaign_id']='different'
            if change=='applied':state['flags']['hmb_'+'a'*32]=1
            with self.assertRaises(BridgeError):classify_loaded_campaign(plan,state)

    def test_named_backup_is_parsed_and_wrong_campaign_backup_is_rejected(self):
        from bridge.return_recovery import preserve_current
        from unittest.mock import Mock
        for correct in (True,False):
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);transfer,session,_=self.fixture(root)
                saves=root/'save games';saves.mkdir()
                native=Mock();api=native.client
                api.VERSION='supported'
                state={'version':'supported','session_active':True,'paused':True,'game_hour':120,'date':'1936.1.2.12'}
                api.ensure_paused.return_value=state;api.health.return_value=state
                native.inspect.return_value={'campaign_id':'c','hour':120,'flags':{'hmb_pending_'+'a'*32:1}}
                health_reads=[]
                def save(route,command=None,**kwargs):
                    if route=='/health':
                        health_reads.append(True)
                        return {'session_active':False} if len(health_reads)==1 else state
                    self.assertEqual(route,'/console')
                    name=command.split(' ',1)[1]
                    text='HOI4txt\ngame_unique_id="'+('c' if correct else 'different')+'"\ndate="1936.1.2.12"\n'
                    (saves/(name+'.hoi4')).write_bytes(text.encode('utf8'))
                    return {'ok':True,'result':'Saved'}
                api.request.side_effect=save
                with patch('bridge.return_recovery.LiveHOI',return_value=native),patch('bridge.return_recovery.time.sleep'):
                    if correct:
                        proof=preserve_current(transfer,{'hoi4_user':str(root)})
                        self.assertEqual(proof['stage'],'backup_verified')
                        self.assertTrue(Path(proof['backup_path']).is_file())
                    else:
                        with self.assertRaises(BridgeError):preserve_current(transfer,{'hoi4_user':str(root)})
                self.assertTrue(transfer.active_file.exists())
                self.assertEqual(sum(call.args[0]=='/console' for call in api.request.call_args_list),1)
                native.apply.assert_not_called()

    def test_wrong_campaign_or_changed_backup_keeps_transfer_locked(self):
        for bad in ('campaign','hash','already_applied'):
            with tempfile.TemporaryDirectory() as folder:
                transfer,session,backup=self.fixture(Path(folder))
                if bad=='campaign':backup['campaign_id']='other'
                if bad=='hash':Path(backup['backup_path']).write_bytes(b'changed')
                if bad=='already_applied':transfer.pending['strategic_result_applied']=True
                with self.assertRaises(BridgeError):abandon_partial(transfer,backup)
                self.assertTrue(transfer.active_file.exists())
                ledger=Ledger(session/'ledger.sqlite')
                self.assertEqual(ledger.db.execute('SELECT status FROM battles').fetchone()[0],'live_failed');ledger.db.close()
