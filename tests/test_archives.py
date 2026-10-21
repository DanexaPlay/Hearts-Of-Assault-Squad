import tempfile,unittest,zipfile
from pathlib import Path
from bridge.archives import open_archive,archive_session
from bridge.core import BridgeError

class ArchiveTests(unittest.TestCase):
    def make(self,path,value='old'):
        with zipfile.ZipFile(path,'w') as z:z.writestr('entry',value)

    def test_shared_indexes_are_closed_after_nested_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'native.pak';self.make(path)
            with archive_session():
                with open_archive(path) as first:self.assertEqual(first.read('entry'),b'old')
                self.assertIsNotNone(first.fp)
                with archive_session():
                    with open_archive(path) as second:self.assertIs(first,second)
            self.assertIsNone(first.fp)
            self.make(path,'new')
            with archive_session():
                with open_archive(path) as changed:
                    self.assertIsNot(first,changed);self.assertEqual(changed.read('entry'),b'new')

    def test_exceptions_and_standalone_reads_close_handles(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'native.pak';self.make(path)
            with self.assertRaises(RuntimeError):
                with archive_session():
                    with open_archive(path) as z:raise RuntimeError('cancelled generation')
            self.assertIsNone(z.fp)
            with open_archive(path) as standalone:self.assertEqual(standalone.read('entry'),b'old')
            self.assertIsNone(standalone.fp)

    def test_changed_archive_cannot_mix_old_index_with_new_generation_data(self):
        import os
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'native.pak';self.make(path)
            with self.assertRaises(BridgeError):
                with archive_session():
                    with open_archive(path) as z:stamp=path.stat().st_mtime_ns
                    os.utime(path,ns=(stamp+1000000,stamp+1000000))
                    with open_archive(path):pass
            self.assertIsNone(z.fp)
