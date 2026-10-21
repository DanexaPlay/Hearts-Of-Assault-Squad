"""User-run status preview. No game input, capture, export or result import."""
import time,uuid
from bridge.core import ROOT,read_json
from bridge.status import TransferStatus


def main():
    path=ROOT/'native_trial/evidence'/('status_'+uuid.uuid4().hex)/'status.json'
    status=TransferStatus(path);status.start_panel()
    for phase in ('capture','generate','open','verify','loaded'):
        status.update(phase,session='preview');time.sleep(3)
    proof=read_json(path.with_suffix('.window.json'))
    if not proof['no_activate_style'] or not proof['foreground_unchanged']:
        raise SystemExit('FAIL: status preview changed focus. Evidence: '+str(path.parent))
    print('PASS: progress panel shown without changing foreground focus.\nEvidence: '+str(path.parent))


if __name__=='__main__':main()
