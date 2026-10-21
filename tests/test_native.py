import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bridge.core import BridgeError
from bridge.native import NativeHOI
from bridge.transition import AutomaticTransfer


class NativeTests(unittest.TestCase):
    def state(self, paused=True, hour=100):
        return {'ok': True, 'version': NativeHOI.VERSION, 'session_active': True,
                'paused': paused, 'game_hour': hour}

    def test_wrong_build_and_menu_rejected(self):
        client = NativeHOI()
        for state in [dict(self.state(), version='other'), dict(self.state(), session_active=False)]:
            with patch.object(client, 'request', return_value=state):
                with self.assertRaises(BridgeError): client.health()

    def test_pause_is_set_only_if_needed_and_verified(self):
        client = NativeHOI()
        with patch.object(client, 'request', return_value=self.state()) as request:
            client.ensure_paused()
            request.assert_called_once_with('/health')
        with patch.object(client, 'request', side_effect=[self.state(False), {'ok': True}, self.state()]) as request:
            self.assertTrue(client.ensure_paused()['paused'])
            self.assertEqual(request.call_args_list[1].args, ('/game/pause', '1'))

    def test_paused_nonzero_selected_speed_is_zeroed_before_named_save(self):
        with tempfile.TemporaryDirectory() as folder:
            transfer=AutomaticTransfer({'hoi4_user':folder},Path(folder)/'sessions')
            transfer.request('HMB_REQUEST: country=GER seq=1')
            client=NativeHOI();selected={**self.state(),'speed':2};stopped={**self.state(),'speed':0}
            with patch.object(client,'ensure_paused',return_value=selected),patch.object(client,'health',side_effect=[stopped,stopped]),patch.object(client,'request',return_value={'ok':True,'result':'Saved'}) as request:
                evidence=client.capture(transfer)
            self.assertEqual(request.call_args_list[0].args,('/lua','hoi4.game_set_speed(0); return true'))
            self.assertEqual(request.call_args_list[1].args,('/console','savegame '+transfer.pending['native_save_name']))
            self.assertEqual(evidence['before']['speed'],0)
            self.assertEqual(evidence['speed_normalization']['before']['speed'],2)
            self.assertTrue(transfer.pending['native_capture_verified'])

    def test_failed_speed_normalization_never_requests_a_save(self):
        for result in ({**self.state(),'speed':2},{**self.state(False),'speed':0},{**self.state(hour=101),'speed':0}):
            with tempfile.TemporaryDirectory() as folder:
                transfer=AutomaticTransfer({'hoi4_user':folder},Path(folder)/'sessions')
                transfer.request('HMB_REQUEST: country=GER seq=1');client=NativeHOI()
                with patch.object(client,'ensure_paused',return_value={**self.state(),'speed':2}),patch.object(client,'health',return_value=result),patch.object(client,'request',return_value={'ok':True}) as request:
                    with self.assertRaises(BridgeError):client.capture(transfer)
                    self.assertEqual(request.call_count,1)
                    self.assertEqual(request.call_args.args[0],'/lua')
                    self.assertNotIn('native_save_name',transfer.pending)
                    self.assertNotIn('native_capture_verified',transfer.pending)

    def test_timed_out_save_is_not_reissued(self):
        with tempfile.TemporaryDirectory() as folder:
            transfer = AutomaticTransfer({'hoi4_user': folder}, Path(folder) / 'sessions')
            transfer.request('HMB_REQUEST: country=GER seq=1')
            client = NativeHOI()
            with patch.object(client, 'ensure_paused', return_value=self.state()), patch.object(client, 'request', side_effect=BridgeError('timeout')) as request:
                with self.assertRaises(BridgeError): client.capture(transfer)
                self.assertTrue(transfer.pending['native_save_name'])
                with self.assertRaises(BridgeError): client.capture(transfer)
                self.assertEqual(request.call_count, 1)

    def test_changed_clock_rejects_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            transfer = AutomaticTransfer({'hoi4_user': folder}, Path(folder) / 'sessions')
            transfer.request('HMB_REQUEST: country=GER seq=1')
            client = NativeHOI()
            with patch.object(client, 'ensure_paused', return_value=self.state()), patch.object(client, 'request', return_value={'ok': True}), patch.object(client, 'health', return_value=self.state(hour=101)):
                with self.assertRaises(BridgeError): client.capture(transfer)
                self.assertNotIn('native_capture_verified', transfer.pending)

    def test_capture_records_evidence_and_ignores_unrelated_save(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'save games').mkdir()
            transfer = AutomaticTransfer({'hoi4_user': folder}, root / 'sessions')
            transfer.request('HMB_REQUEST: country=GER seq=1')
            client = NativeHOI()
            with patch.object(client, 'ensure_paused', return_value=self.state()), patch.object(client, 'request', return_value={'ok': True, 'result': 'Saved'}), patch.object(client, 'health', return_value=self.state()):
                client.capture(transfer)
            self.assertTrue(transfer.pending['native_capture_verified'])
            (root / 'save games' / 'unrelated.hoi4').write_text('unrelated')
            self.assertIsNone(transfer.find_fresh_snapshot())
            self.assertIsNone(transfer.find_fresh_snapshot())
            expected = root / 'save games' / (transfer.pending['native_save_name'] + '_temp.hoi4')
            expected.write_text('captured')
            self.assertIsNone(transfer.find_fresh_snapshot())
            self.assertEqual(transfer.find_fresh_snapshot(), expected.resolve())
