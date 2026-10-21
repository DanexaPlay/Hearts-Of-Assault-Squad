"""Reopen the installed test mission and verify its initial autosave only.

This rehearsal neither captures nor changes HOI4 and never imports a result.
"""
import shutil,time,uuid
from pathlib import Path
from bridge.core import ROOT,BridgeError,config,read_json,write_json,digest
from bridge.transition import AutomaticTransfer,worker_lock
from bridge.mow_launch import start


def main(source=None,require_closed=False):
    cfg=config()
    with worker_lock(ROOT/'sessions/automatic'):
        if source is None:
            active=read_json(ROOT/'sessions/automatic/active-transition.json')
            source=active['session']
        source=Path(source).resolve()
        if not source.is_relative_to((ROOT/'sessions/automatic').resolve()):raise BridgeError('Invalid source session')
        from bridge.launch_native import running
        if require_closed and running('mowas_2.exe'):
            raise BridgeError('Close MoW first: this trial checks a fresh executable launch')
        previous=read_json(source/'transition.json')
        if previous.get('strategic_result_applied') is not True:
            raise BridgeError('Finish the existing strategic transfer before this independent loading rehearsal')
        from bridge.mission_paths import installed_mission
        target=Path(cfg['mow_live_mod']);mission=installed_mission(target,previous['installation'])
        if digest(mission.read_bytes())!=previous['installation']['mission_sha256']:
            raise BridgeError('Installed mission changed; no test launched')
        root=ROOT/'native_trial/evidence'/('mow_load_'+uuid.uuid4().hex)
        session=root/'probe';session.mkdir(parents=True)
        for name in ['battle.json','roster.json']:shutil.copy2(source/name,session/name)
        transfer=AutomaticTransfer(cfg,root)
        transfer.pending={'status':'ready','path':str(session.resolve()),'requested_at_ns':time.time_ns(),
            'installation':previous['installation'],'loading_rehearsal_only':True}
        transfer._record()
        print('Opening the installed test mission. HOI4 is not changed. Leave MoW in the foreground.',flush=True)
        start(transfer,cfg,ROOT)
        end=time.monotonic()+180
        while time.monotonic()<end:
            loaded=read_json(session/'loaded-mission.json') if transfer.pending.get('engine_load_verified') else transfer.collect_loaded()
            if loaded:
                transfer.pending['mow_launch'].update(stage='mission_loaded',game_load_verified=True)
                transfer._record()
                write_json(session/'mow-launch.json',transfer.pending['mow_launch'])
                write_json(session/'mow-launch-verification.json',{'stage':'verified','battle_id':loaded['battle_id'],
                    'actors':loaded['actors'],'hoi4_changed':False,'result_import_enabled':False,
                    'closed_game_required':require_closed,'launch_method':transfer.pending['mow_launch'].get('launch_method'),
                    'single_attempt':True,'launch_events':transfer.pending['mow_launch'].get('events',[])})
                print('PASS: correct MoW mission and roster loaded automatically. No HOI4 changes.\nEvidence: '+str(session),flush=True)
                return
            time.sleep(1)
        raise BridgeError('No matching initial MoW autosave within 180 seconds')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--source');parser.add_argument('--require-closed',action='store_true');args=parser.parse_args()
    try:main(args.source,args.require_closed)
    except (OSError,BridgeError) as error:raise SystemExit('Loading trial stopped: '+str(error))
