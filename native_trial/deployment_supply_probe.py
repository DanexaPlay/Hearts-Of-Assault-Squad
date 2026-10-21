"""Isolated native barrier/inventory trial; never imports results into HOI4."""
import copy,re,time,uuid,shutil
from pathlib import Path
from bridge.core import ROOT,BridgeError,config,read_json,write_json,digest
from bridge.gem import generate
from bridge.ammunition import audit_ammunition
from bridge.transition import AutomaticTransfer,worker_lock,install_generated_mod,release_completed

def boundary_counts(text):
    return {'obstacles':len(re.findall(r'\{Entity "obstacle" ',text)),
            'markers':len(re.findall(r'\{Entity "flagstaff" ',text)),
            'vehicle_walls':len(re.findall(r'\{Entity "hmb_prep_vehicle_wall" ',text))}

def main(defender=False):
    from bridge.launch_native import running
    from bridge.desktop import GameDesktop
    from bridge.mow_launch import start,engine_failure
    cfg=config()
    with worker_lock(ROOT/'sessions/automatic'):
        previous=AutomaticTransfer(cfg,ROOT/'sessions/automatic')
        if previous.pending:
            if previous.pending.get('strategic_result_applied') and previous.pending['status']=='result_ready':
                release_completed(previous,cfg,allow_menu=True)
            else:raise BridgeError('Finish or explicitly cancel the existing strategic transfer first')
        if running('mowas_2_ed.exe'):raise BridgeError('Close the editor before this game trial')
        if running('mowas_2.exe'):GameDesktop(cfg,ROOT).confirm_mow_menu(restore_focus=True)
        else:print('MoW is closed; the trial will launch it after installing resources.',flush=True)
        b=copy.deepcopy(read_json(ROOT/'sessions/formations-game/battle.json'))
        b.update(id=uuid.uuid4().hex,player_side='defender' if defender else 'attacker',
            source='deployment_supply_fixture: saved templates in synthetic encounter; no strategic result import')
        for side,percent in [('attacker','25'),('defender','100')]:
            for division in b[side]['divisions']:division['supply_raw']=percent
        settings={**cfg,'preparation_boundaries':True,'supply_ammunition':True,
            'preparation_seconds':120,'battle_timer_seconds':180,'preparation_probe_autosave':True}
        root=ROOT/'native_trial/evidence'/('deployment_supply_'+b['id']);session=root/'probe'
        print('Preparing deployment/supply trial. HOI4 is not changed. Test preparation: 120 seconds.',flush=True)
        mission=generate(b,settings,session)
        installed=install_generated_mod(session/'mow_mod',cfg['mow_live_mod'],session)
        if installed['requires_engine_restart']:print('Checking registration of deployment resources; an engine opened after installation will be reused.',flush=True)
        transfer=AutomaticTransfer(cfg,root)
        transfer.pending={'status':'ready','path':str(session.resolve()),'battle_id':b['id'],
            'requested_at_ns':time.time_ns(),'installation':installed,'mission':mission,
            'loading_rehearsal_only':True,'result_import_enabled':False}
        transfer._record();start(transfer,cfg,ROOT)
        deadline=time.monotonic()+160
        while time.monotonic()<deadline:
            loaded=read_json(session/'loaded-mission.json') if transfer.pending.get('engine_load_verified') else transfer.collect_loaded()
            if loaded:break
            failure=engine_failure(transfer,cfg)
            if failure:raise BridgeError(failure)
            time.sleep(1)
        else:raise BridgeError('No verified initial mission snapshot')
        roster=read_json(session/'roster.json');text=Path(loaded['evidence']['path']).read_text(encoding='utf-8-sig')
        audit=audit_ammunition(roster,text)
        counts=boundary_counts(text);plan=read_json(session/'preparation.json')
        if counts!={'obstacles':plan['navigation_obstacles'],'markers':plan['visible_markers'],'vehicle_walls':plan['vehicle_contact_walls']}:
            raise BridgeError('Saved deployment obstacles/markers do not match the generated plan: '+str(counts))
        write_json(session/'initial-verification.json',{'ammunition':audit,'boundaries':counts,'hoi4_changed':False,'result_import_enabled':False})
        print('PASS: native reserve ammunition and deployment entities verified.\n'
            'During preparation, try normal move orders AND direct control across your flag line with infantry and a vehicle.\n'
            'After the 120-second preparation, check that the flags disappear and crossing becomes possible.\n'
            'No need to finish the battle. HOI4 is not changed.\nEvidence: '+str(session),flush=True)
        initial_hash=loaded['evidence']['sha256'];stable={};deadline=time.monotonic()+210
        while time.monotonic()<deadline:
            for native in (Path(cfg['mow_progress']).parent/'save').glob('autosave*/mission.scn'):
                if native.stat().st_mtime_ns<transfer.pending['requested_at_ns']:continue
                raw=native.read_bytes();sha=digest(raw)
                if sha==initial_hash or b['id'].encode() not in raw:continue
                if stable.get(str(native))!=sha:stable[str(native)]=sha;continue
                text=raw.decode('utf-8-sig')
                if boundary_counts(text)!={'obstacles':0,'markers':0,'vehicle_walls':0}:continue
                destination=session/'released-snapshot';destination.mkdir(exist_ok=True)
                for name in ('mission.scn','game.scn'):
                    source=native.parent/name
                    if source.is_file():shutil.copy2(source,destination/name)
                write_json(session/'release-verification.json',{'stage':'all preparation entities removed in native snapshot','battle_id':b['id'],'mission_sha256':sha,'movement_enforcement':'manual verification still required','hoi4_changed':False})
                print('PASS: preparation obstacles and markers removed automatically. Report whether movement was blocked before release and allowed afterward.',flush=True)
                return
            failure=engine_failure(transfer,cfg)
            if failure:raise BridgeError(failure)
            time.sleep(1)
        raise BridgeError('No verified post-preparation snapshot; the prepared mission is retained')

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--defender',action='store_true');args=parser.parse_args()
    try:main(args.defender)
    except (OSError,BridgeError) as error:raise SystemExit('Deployment/supply trial stopped: '+str(error))
