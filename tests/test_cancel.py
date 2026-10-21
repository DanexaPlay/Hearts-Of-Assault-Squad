import tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from bridge.core import BridgeError,Ledger,read_json
from bridge.transition import AutomaticTransfer
from bridge.cancel_transition import cancel,verified_cancel


class CancelTests(unittest.TestCase):
    def transfer(self,folder,status='exported'):
        auto=AutomaticTransfer({'hoi4_user':folder},Path(folder)/'sessions')
        auto.request('HMB_REQUEST: country=GER seq=1')
        auto.pending.update(status='mission_loaded',battle_id='a'*32);auto._record()
        session=Path(auto.pending['path']);ledger=Ledger(session/'ledger.sqlite')
        with ledger.db:ledger.db.execute('INSERT INTO battles VALUES(?,?,?,NULL)',('a'*32,'{}',status))
        ledger.db.close();return auto,session

    def test_explicit_cancel_archives_and_allows_a_new_request_without_deleting_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            auto,session=self.transfer(folder);(session/'roster.json').write_text('keep')
            report=cancel(auto,{'kind':'recognized_mow_menu','scene':'mow_main'})
            self.assertFalse(report['hoi4_modified']);self.assertFalse(report['losses_imported'])
            self.assertFalse(auto.active_file.exists());self.assertIsNone(auto.pending)
            self.assertEqual(read_json(session/'transition.json')['status'],'cancelled')
            self.assertEqual((session/'roster.json').read_text(),'keep')
            ledger=Ledger(session/'ledger.sqlite')
            self.assertEqual(ledger.db.execute('SELECT status FROM battles').fetchone()[0],'cancelled');ledger.db.close()
            self.assertIsNotNone(auto.request('HMB_REQUEST: country=GER seq=2'))
            self.assertNotEqual(Path(auto.pending['path']),session)

    def test_active_scene_completed_result_or_partial_return_cannot_be_cancelled(self):
        for case in ['no_exit','result','return_stage','applied','live_applying','live_failed','ledger_applied']:
            with tempfile.TemporaryDirectory() as folder:
                ledger_status=case if case in ('live_applying','live_failed') else 'applied' if case=='ledger_applied' else 'exported'
                auto,session=self.transfer(folder,ledger_status)
                proof={'kind':'mow_process_closed'}
                if case=='no_exit':proof={'kind':'game_over_overlay'}
                if case=='result':(session/'result.json').write_text('{}')
                if case=='return_stage':auto.pending['native_return_stage']='applying_direct'
                if case=='applied':auto.pending['strategic_result_applied']=True
                with self.assertRaises(BridgeError):cancel(auto,proof)
                self.assertTrue(auto.active_file.exists());self.assertIsNotNone(auto.pending)
                self.assertFalse((session/'cancellation.json').exists())

    def test_terminal_autosave_blocks_cancellation_even_if_worker_missed_it(self):
        auto=Mock();auto.pending={'status':'mission_loaded'};auto.collect_final.side_effect=[None,{'winner':'attacker'}]
        with patch('bridge.launch_native.running',return_value=False),patch('bridge.cancel_transition.time.sleep'),patch('bridge.cancel_transition.cancel') as abandon:
            with self.assertRaises(BridgeError):verified_cancel(auto,{})
            abandon.assert_not_called()

    def test_menu_must_be_verified_before_any_cancellation(self):
        auto=Mock();auto.pending={'status':'mission_loaded'}
        with patch('bridge.launch_native.running',return_value=True),patch('bridge.desktop.GameDesktop') as desktop,patch('bridge.cancel_transition.cancel') as abandon:
            desktop.return_value.confirm_mow_menu.side_effect=BridgeError('still playing')
            with self.assertRaises(BridgeError):verified_cancel(auto,{})
            abandon.assert_not_called();auto.collect_final.assert_not_called()

    def test_cancel_recovers_if_process_stopped_after_ledger_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            auto,session=self.transfer(folder,'cancelled')
            auto.pending['status']='cancelling';auto._record()
            auto=AutomaticTransfer({'hoi4_user':folder},Path(folder)/'sessions')
            cancel(auto,{'kind':'mow_process_closed'})
            self.assertFalse(auto.active_file.exists())
