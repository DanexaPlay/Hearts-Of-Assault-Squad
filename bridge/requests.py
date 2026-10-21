"""Read new local opt-in log messages; never replay old requests at startup."""
import codecs
from pathlib import Path

class RequestWatcher:
    def __init__(self,path):
        self.path=Path(path); self.offset=self.path.stat().st_size if self.path.exists() else 0
        self.decoder=codecs.getincrementaldecoder('utf8')('replace'); self.pending=''
    def poll(self):
        if not self.path.exists(): return []
        size=self.path.stat().st_size
        if size<self.offset:
            self.offset=0; self.pending=''; self.decoder.reset()
        with self.path.open('rb') as stream:
            stream.seek(self.offset); data=stream.read(262144); self.offset=stream.tell()
        text=self.pending+self.decoder.decode(data)
        lines=text.split('\n'); self.pending=lines.pop()
        return [line.strip() for line in lines if 'HMB_REQUEST:' in line]
