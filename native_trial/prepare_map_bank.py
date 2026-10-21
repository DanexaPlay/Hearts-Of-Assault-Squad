"""One-time closed-engine installation, with no HOI4 writes."""
import uuid,subprocess,shutil,re
from pathlib import Path
from bridge.core import ROOT,BridgeError,config,read_json,write_json
from bridge.transition import AutomaticTransfer,worker_lock
from bridge.launch_native import running
from bridge.map_bank import prepare_bank,supported_maps

def main(launch=False,restore=False):
    cfg=config()
    with worker_lock(ROOT/'sessions/automatic'):
        if running('mowas_2.exe') or running('mowas_2_ed.exe'):
            raise BridgeError('Close Men of War and its editor before preparing the map bank')
        if AutomaticTransfer(cfg,ROOT/'sessions/automatic').pending:
            raise BridgeError('Finish or cancel the current strategic transfer first')
        output=ROOT/'native_trial/evidence'/('map_bank_'+uuid.uuid4().hex)
        if restore:
            from bridge.transition import install_generated_mod
            target=Path(cfg['mow_live_mod']).resolve();archive=output/'bank-backup'
            for folder in list((target/'resource/map/single/hmb').glob('map_*')):
                destination=archive/folder.name
                if not re.fullmatch(r'map_[0-9a-f]{16}',folder.name) or not folder.resolve().is_relative_to(target):raise BridgeError('Unsafe bank restore path')
                if not destination.resolve().is_relative_to(output.resolve()):raise BridgeError('Unsafe bank backup path')
                archive.mkdir(parents=True,exist_ok=True);shutil.move(str(folder),str(destination))
            marker=target/'hmb-map-bank.json'
            if marker.exists():
                archive.mkdir(parents=True,exist_ok=True);shutil.move(str(marker),str(archive/marker.name))
            source=ROOT/'sessions/readiness-difficulty-proof/mow_mod'
            install_generated_mod(source,target,output)
            write_json(output/'config-before-restore.json',cfg)
            write_json(ROOT/'config.json',{**cfg,'preinstalled_map_slots':False})
            print('RESTORED: regular fixed-path mission. Restart MoW before using it.\nEvidence: '+str(output),flush=True)
            return
        maps,unsupported=supported_maps(cfg)
        settings={**cfg,'maps':{'catalogue':maps},'winter_maps':{}}
        bank=prepare_bank(settings,read_json(ROOT/'examples/battle.example.json'),output)
        if unsupported:print('Not added (native capture anchors require separate validation): '+', '.join(unsupported),flush=True)
        print('READY: '+str(len(bank['slots']))+' complete native map slots installed. Start MoW once to register them.\nNo HOI4 changes. Live terrain verification is still required.\nEvidence: '+str(output),flush=True)
        if launch:
            exe=Path(cfg['mow'])/'mowas_2.exe'
            subprocess.Popen([str(exe)],cwd=exe.parent)
            print('MoW started from its game folder. Leave its mission menu open for calibration.',flush=True)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--launch',action='store_true');parser.add_argument('--restore',action='store_true');args=parser.parse_args()
    try:main(args.launch,args.restore)
    except (OSError,BridgeError) as error:raise SystemExit('Map-bank preparation stopped: '+str(error))
