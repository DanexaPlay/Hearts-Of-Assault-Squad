"""User-run isolated combined-arms rehearsal; never imports strategic losses."""
import copy,time,uuid
from pathlib import Path
from bridge.core import ROOT,BridgeError,config,read_json,write_json
from bridge.gem import generate
from bridge.transition import AutomaticTransfer,worker_lock,install_generated_mod


def fixture_battle(source):
    battle=copy.deepcopy(source)
    battle.update(id=uuid.uuid4().hex,player_side='defender',
        source='tactical_ai_test_fixture: real saved templates, synthetic encounter')
    return battle


def main(readiness=False):
    from bridge.launch_native import running
    from bridge.cancel_transition import verified_cancel
    from bridge.desktop import GameDesktop
    from bridge.mow_launch import start,engine_failure
    cfg=config()
    with worker_lock(ROOT/'sessions/automatic'):
        automatic=AutomaticTransfer(cfg,ROOT/'sessions/automatic')
        # The user explicitly cancelled the preceding battle. Verify scene
        # exit and refuse any terminal result or partially applied return.
        if automatic.pending:
            verified_cancel(automatic,cfg)
            print('Previous unfinished battle cancelled. HOI4 unchanged.',flush=True)
        elif running('mowas_2.exe'):
            GameDesktop(cfg,ROOT).confirm_mow_menu(restore_focus=True)
        if running('mowas_2_ed.exe'):raise BridgeError('Close the MoW editor before this trial')
        source=ROOT/('sessions/readiness-difficulty-proof/battle.json' if readiness else 'sessions/formations-game/battle.json')
        if not source.is_file():raise BridgeError('The verified formation fixture is missing')
        original=read_json(source)
        battle=fixture_battle(original)
        if readiness:
            battle['player_side']=original.get('player_side','attacker')
            battle['source']='readiness_difficulty_test_fixture: verified live organisation and saved campaign difficulty'
        root=ROOT/'native_trial/evidence'/('tactical_ai_'+battle['id'])
        session=root/'probe'
        print('Preparing isolated organisation/difficulty trial. No HOI4 changes.' if readiness else
            'Preparing isolated AI trial. You control the Soviet infantry; German combined arms are the enemy.',flush=True)
        report=generate(battle,cfg,session)
        installation=install_generated_mod(session/'mow_mod',cfg['mow_live_mod'],session)
        transfer=AutomaticTransfer(cfg,root)
        transfer.pending={'status':'ready','path':str(session.resolve()),'battle_id':battle['id'],
            'requested_at_ns':time.time_ns(),'installation':installation,'mission':report,
            'loading_rehearsal_only':True,'result_import_enabled':False}
        transfer._record()
        start(transfer,cfg,ROOT)
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            loaded=read_json(session/'loaded-mission.json') if transfer.pending.get('engine_load_verified') else transfer.collect_loaded()
            if loaded:
                write_json(session/'ai-load-verification.json',{
                    'battle_id':battle['id'],'actors':loaded['actors'],
                    'hoi4_changed':False,'result_import_enabled':False,
                    'stage':'engine loaded; tactical behaviour still requires observation'})
                instructions=('PASS: organisation-scaled mission and roster loaded. No HOI4 changes.\n'
                    'No need to save again or finish the battle. Optional save: HMB_readiness_probe.\n' if readiness else
                    'PASS: isolated AI mission loaded. No HOI4 changes.\n'
                    'After preparation, observe enemy infantry, tanks and gun for 2-3 minutes.\n'
                    'Save as HMB_ai_director_probe.\n')
                print(instructions+'Evidence: '+str(session),flush=True)
                return
            failure=engine_failure(transfer,cfg)
            if failure:raise BridgeError(failure)
            time.sleep(1)
        raise BridgeError('No matching initial MoW autosave within 180 seconds')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--readiness',action='store_true');args=parser.parse_args()
    try:main(args.readiness)
    except (OSError,BridgeError) as error:raise SystemExit('AI trial stopped: '+str(error))
