import tempfile,unittest
from pathlib import Path
from bridge.core import write_json
from bridge.snapshot_cleanup import cleanup_plan,cleanup

class CleanupTests(unittest.TestCase):
    def test_only_old_verified_identical_bridge_captures_are_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);sessions=base/'sessions';saves=base/'user/save games'
            sessions.mkdir();saves.mkdir(parents=True);cfg={'hoi4_user':str(base/'user'),'retained_completed_snapshots':3}
            for i in range(8):
                name='HMB_transition_'+format(i,'032x');session=sessions/str(i);session.mkdir()
                record={'native_save_name':name,'requested_at_ns':i,'strategic_result_applied':i<5,'native_return_stage':'verified' if i<5 else 'unattempted'}
                write_json(session/'transition.json',record)
                (session/'hoi4-source.hoi4').write_bytes(b'original')
                (saves/(name+'.hoi4')).write_bytes(b'changed by player' if i==1 else b'original')
            manual=saves/'GER_campaign.hoi4';manual.write_bytes(b'manual')
            plan=cleanup_plan(cfg,sessions)
            self.assertEqual(len(plan['files']),1)
            victim=saves/('HMB_transition_'+'0'*32+'.hoi4')
            self.assertEqual(Path(plan['files'][0]['path']),victim)
            self.assertTrue(victim.exists())  # Planning is read-only.
            result=cleanup(cfg,sessions)
            self.assertEqual(result['bytes_removed'],len(b'original'))
            self.assertFalse(victim.exists());self.assertTrue((sessions/'0/hoi4-source.hoi4').exists())
            self.assertTrue(manual.exists());self.assertEqual(len(list(saves.glob('HMB_transition*'))),7)
            self.assertFalse(cleanup(cfg,sessions)['removed'])

    def test_unarchived_files_and_forged_names_are_never_candidates(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);sessions=root/'sessions';sessions.mkdir();saves=root/'save games';saves.mkdir()
            for i,name in enumerate(('GER_campaign','../escape',None,'HMB_transition_'+'a'*32)):
                session=sessions/str(i);session.mkdir()
                write_json(session/'transition.json',{'native_save_name':name,'strategic_result_applied':True,'native_return_stage':'verified'})
            (saves/('HMB_transition_'+'a'*32+'.hoi4')).write_bytes(b'no backup')
            self.assertFalse(cleanup_plan({'hoi4_user':str(root)},sessions)['files'])
