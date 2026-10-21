import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from bridge.core import read_json
from bridge.status import TransferStatus


class StatusTests(unittest.TestCase):
    def test_manual_loading_names_the_actual_bank_mission(self):
        from bridge.core import write_json
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);session=root/'battle';session.mkdir()
            write_json(session/'mission_manifest.json',{'source_map':'multi/1v1_winter_fields','mission_path':'single/hmb/map_12f59694d2e94813'})
            status=TransferStatus(root/'status.json')
            message=status.update('manual',str(session))
            self.assertIn('«1v1_winter_fields»',message['detail'])
            self.assertIn('Выйдите в главное меню',message['detail'])
            self.assertIn('повторно не нажимайте',message['detail'])
            self.assertFalse(message['busy'])
            self.assertNotIn('hide_after_ns',message)

    def test_rejected_second_battle_has_a_clear_persistent_message(self):
        with tempfile.TemporaryDirectory() as folder:
            status=TransferStatus(Path(folder)/'status.json')
            message=status.update('rejected','first',error='A tactical transition is already active')
            self.assertIn('Сначала завершите текущий бой',message['user_error'])
            self.assertFalse(message['busy']);self.assertNotIn('hide_after_ns',message)
            self.assertEqual(message['session'],'first')

    def test_generation_keeps_the_same_elapsed_origin_and_a_new_battle_resets_it(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'status.json';status=TransferStatus(p)
            with patch('bridge.status.time.time_ns',side_effect=[100,200,300]):
                status.update('capture','first');message=status.update('generate','first')
                self.assertEqual(message['started_at_ns'],100)
                self.assertEqual(read_json(p)['phase'],'generate')
                self.assertTrue(message['busy'])
                self.assertEqual(status.update('capture','second')['started_at_ns'],300)

    def test_only_success_auto_hides_and_errors_remain_readable(self):
        with tempfile.TemporaryDirectory() as folder:
            status=TransferStatus(Path(folder)/'status.json')
            done=status.update('loaded','battle')
            self.assertFalse(done['busy']);self.assertIn('hide_after_ns',done)
            error=status.update('error','battle',error='Exact reason')
            self.assertEqual(error['error'],'Exact reason');self.assertFalse(error['busy'])
            self.assertNotIn('hide_after_ns',error)
            reason='Game lost foreground focus; UI transfer stopped'
            error=status.update('error','battle',error=reason)
            self.assertEqual(error['error'],reason)
            self.assertIn('Окно игры',error['user_error'])
            with self.assertRaises(ValueError):status.update('unknown')

    def test_status_io_failure_does_not_abort_a_game_transfer(self):
        status=TransferStatus('example')
        with patch('bridge.status.write_json',side_effect=OSError('unavailable')):
            self.assertEqual(status.update('generate','battle')['phase'],'generate')
