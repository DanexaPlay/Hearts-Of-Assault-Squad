import tempfile,unittest
from pathlib import Path
from bridge.requests import RequestWatcher

class RequestTests(unittest.TestCase):
    def test_ignores_old_requests_and_waits_for_complete_line(self):
        with tempfile.TemporaryDirectory() as folder:
            log=Path(folder)/'game.log'; log.write_bytes(b'HMB_REQUEST: old\n')
            watcher=RequestWatcher(log); self.assertEqual(watcher.poll(),[])
            with log.open('ab') as stream: stream.write(b'normal\nHMB_REQUEST: new')
            self.assertEqual(watcher.poll(),[])
            with log.open('ab') as stream: stream.write(b'\n')
            self.assertEqual(watcher.poll(),['HMB_REQUEST: new'])
            self.assertEqual(watcher.poll(),[])
            log.write_bytes(b'HMB_REQUEST: restart\n')
            self.assertEqual(watcher.poll(),['HMB_REQUEST: restart'])

if __name__=='__main__': unittest.main()
