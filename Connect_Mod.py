from pathlib import Path
from bridge.core import config
from bridge.install import connect_mod

if __name__=='__main__':
    try:
        report=connect_mod(config(),Path(__file__).resolve().parent)
        print('Connected: '+report['editable_mod'])
        if report.get('backup'):print('Old mod preserved: '+report['backup'])
    except Exception as error:
        print('Connection failed; '+str(error))
        raise SystemExit(1)
