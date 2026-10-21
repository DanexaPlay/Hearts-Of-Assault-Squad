"""User-run three-map warm-process rehearsal, with no HOI4 result import."""
import copy,time,uuid,re,shutil,zipfile
from pathlib import Path
from bridge.core import ROOT,BridgeError,config,read_json,write_json,digest
from bridge.gem import generate
from bridge.transition import AutomaticTransfer,worker_lock,install_generated_mod


def verify_map(loaded,mission,cfg,session):
    native=Path(loaded['evidence']['original_path'])
    saved=native.parent/'map.scn'
    if digest(native.read_bytes())!=loaded['evidence']['sha256']:raise BridgeError('Initial autosave changed before map verification')
    raw=saved.read_bytes();text=raw.decode('utf-8-sig')
    with zipfile.ZipFile(Path(cfg['mow'])/'resource/map.pak') as z:
        original=z.read('map/'+mission['map']+'/map').decode('utf8')
    def bounds(t):return [float(v) for v in re.search(r'\{pather ([^}]+)\}',t)[1].split()]
    def entities(t):return {int(uid,16):name for name,uid in re.findall(r'\{Entity "([^"\r\n]+)" (0x[0-9a-fA-F]+)',t)}
    expected=entities(original);actual=entities(text)
    if bounds(text)!=bounds(original) or any(actual.get(uid)!=name for uid,name in expected.items()):
        raise BridgeError('Loaded static map or bounds differ from the selected native map')
    if digest(native.read_bytes())!=loaded['evidence']['sha256'] or saved.read_bytes()!=raw:
        raise BridgeError('Map autosave changed during verification')
    shutil.copy2(saved,session/'verified-map.scn')
    for name in ('preview.jpg','screenshot.jpg'):
        if (native.parent/name).is_file():shutil.copy2(native.parent/name,session/name)
    proof={'source_map':mission['map'],'map_scene_sha256':digest(raw),'static_entities_matched':len(expected),'bounds':bounds(text)}
    write_json(session/'map-verification.json',proof)
    return proof


def main(all_maps=False):
    from bridge.launch_native import process_ids,running,process_started_at_ns
    from bridge.desktop import GameDesktop
    from bridge.mow_launch import start,engine_failure
    cfg=config()
    with worker_lock(ROOT/'sessions/automatic'):
        if AutomaticTransfer(cfg,ROOT/'sessions/automatic').pending:
            raise BridgeError('Finish or cancel the active strategic transfer first')
        baseline=process_ids('mowas_2.exe')
        if len(baseline)!=1:raise BridgeError('Leave exactly one MoW game open at its main menu')
        if running('mowas_2_ed.exe'):raise BridgeError('Close the MoW editor before this trial')
        desktop=GameDesktop(cfg,ROOT);desktop.confirm_mow_menu(restore_focus=True)
        original=read_json(ROOT/'sessions/readiness-difficulty-proof/battle.json')
        root=ROOT/'native_trial/evidence'/('unique_maps_'+uuid.uuid4().hex)
        root.mkdir(parents=True)
        trial={'process_ids':baseline,'hoi4_changed':False,'result_import_enabled':False,'stages':[]}
        write_json(root/'trial.json',trial)
        from bridge.map_bank import validate_installed_bank
        bank=validate_installed_bank(cfg['mow_live_mod'])
        target=Path(cfg['mow_live_mod']);receipt=target/'.hmb-engine-restart.json'
        if process_started_at_ns(baseline[0])<=max((target/'hmb-map-bank.json').stat().st_mtime_ns,receipt.stat().st_mtime_ns if receipt.exists() else 0):
            raise BridgeError('Restart MoW once after preparing the map bank')
        receipt.unlink(missing_ok=True)
        settings={**cfg,'preparation_seconds':5,'battle_timer_seconds':30,'capture_score_to_win':100,
            'preinstalled_map_slots':True,'unique_mission_paths':False,'linked_map_resources':False}
        cases=[('plains',slot['source_map']) for slot in bank['slots']] if all_maps else [(t,None) for t in ('river','plains','forest')]
        count=len(cases)
        trial.update(test_kind='preinstalled_complete_map_bank',expected_maps=count)
        for index,(terrain,source_map) in enumerate(cases,1):
            if process_ids('mowas_2.exe')!=baseline:raise BridgeError('MoW process changed; warm-map trial is not valid')
            desktop.confirm_mow_menu(restore_focus=True)
            b=copy.deepcopy(original)
            b.update(id=uuid.uuid4().hex,terrain=terrain,river_crossing=False,weather={'known':False},
                source='unique_maps_test_fixture: no strategic result import')
            b.pop('mission_path',None)
            session=root/('stage_'+str(index));print('Preparing map '+str(index)+'/'+str(count)+': '+(source_map or terrain),flush=True)
            stage_settings={**settings,'maps':{'plains':[source_map]}} if source_map else settings
            mission=generate(b,stage_settings,session)
            installation=install_generated_mod(session/'mow_mod',cfg['mow_live_mod'],session)
            if installation['requires_engine_restart']:
                raise BridgeError('Shared resources still require a restart. Close MoW, reopen it, and rerun this trial.')
            transfer=AutomaticTransfer(cfg,root)
            transfer.pending={'status':'ready','path':str(session.resolve()),'battle_id':b['id'],
                'requested_at_ns':time.time_ns(),'installation':installation,'mission':mission,
                'loading_rehearsal_only':True,'result_import_enabled':False}
            transfer._record();start(transfer,cfg,ROOT)
            end=time.monotonic()+150
            while time.monotonic()<end:
                loaded=read_json(session/'loaded-mission.json') if transfer.pending.get('engine_load_verified') else transfer.collect_loaded()
                if loaded:break
                failure=engine_failure(transfer,cfg)
                if failure:raise BridgeError(failure)
                time.sleep(1)
            else:raise BridgeError('No matching mission acknowledgement')
            if process_ids('mowas_2.exe')!=baseline:raise BridgeError('MoW process changed during loading')
            if transfer.pending['mow_launch']['launch_method']!='reuse_running_game':raise BridgeError('Warm-process loading was not used')
            map_proof=verify_map(loaded,mission,cfg,session)
            trial['stages'].append({'battle_id':b['id'],'mission_path':b['mission_path'],'resource_path':b.get('map_resource_path'),'map':mission['map'],
                'actors':loaded['actors'],'map_verification':map_proof,'process_ids':baseline,'requires_engine_restart':False})
            write_json(root/'trial.json',trial)
            print('PASS map '+str(index)+'/'+str(count)+': correct mission/roster, same MoW process.',flush=True)
            if index<count:
                input('Return to the MoW MAIN MENU, then return here and press Enter. Do not close MoW.\n')
            else:
                print('Leave the final mission running. Its test timer ends after 30 seconds (+5 preparation).',flush=True)
                end=time.monotonic()+150
                while time.monotonic()<end:
                    result=transfer.collect_final()
                    if result:
                        trial.update(terminal_result_verified=True,result_battle_id=result['battle_id'],
                            result_winner=result['winner'],terrain_visual_check_pending=True,
                            stage=str(count)+' map records and final result verified; terrain visuals pending')
                        write_json(root/'trial.json',trial)
                        print('PASS: '+str(count)+' map records and final result verified without restarting MoW. Terrain screenshots saved for visual verification.\nEvidence: '+str(root),flush=True)
                        return
                    failure=engine_failure(transfer,cfg)
                    if failure:raise BridgeError(failure)
                    time.sleep(1)
                raise BridgeError('No verified final result from the last map')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--all-maps',action='store_true');args=parser.parse_args()
    try:main(args.all_maps)
    except (OSError,BridgeError,EOFError) as error:raise SystemExit('Unique-map trial stopped: '+str(error))
