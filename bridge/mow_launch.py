"""User-run Steam launch and bounded MoW menu navigation.

HOI4 capture and return remain native. Screen matching is restricted to MoW's
menu; only the generated mission's UUID/roster autosave acknowledges loading.
"""
import time,subprocess
from pathlib import Path
from .core import BridgeError,digest,write_json


def startup_log_ready(path,baseline,started_at_ns):
    """Only a new main-page entry counts, whether the log truncates or appends."""
    try:
        if path.stat().st_mtime_ns<started_at_ns:return False
        data=path.read_bytes()
    except OSError:return False
    fresh=data[len(baseline):] if baseline and data.startswith(baseline) else data
    return b'Opening main page' in fresh


def existing_fresh_engine(target,log):
    """Accept a user-started engine only after the last resource installation.

    Main-page log alone can be stale; pair it with read-only process creation
    time and the unchanged restart receipt. No input or process termination.
    """
    from .launch_native import process_ids,process_started_at_ns
    receipt=Path(target)/'.hmb-engine-restart.json'
    if not receipt.is_file():return None
    try:
        changed=receipt.stat().st_mtime_ns
        pids=process_ids('mowas_2.exe')
        if len(pids)!=1:return None
        started=process_started_at_ns(pids[0])
        if started<=changed or not startup_log_ready(Path(log),b'',started):return None
        return {'process_id':pids[0],'process_started_at_ns':started,
                'resource_receipt_mtime_ns':changed,'resource_receipt_sha256':digest(receipt.read_bytes())}
    except (OSError,BridgeError):return None


def start(automatic,cfg,root,progress=None):
    from .launch_native import running
    from .desktop import GameDesktop
    pending=automatic.pending
    if not pending or pending['status']!='ready':raise BridgeError('No installed tactical mission awaiting launch')
    if pending.get('mow_launch'):raise BridgeError('MoW launch already attempted; refusing a second launch')
    installation=pending.get('installation',{})
    target=Path(installation.get('target',''))
    from .mission_paths import installed_mission
    mission=installed_mission(target,installation)
    if target.name!='HOI4_MoW_Bridge' or not mission.is_file() or digest(mission.read_bytes())!=installation.get('mission_sha256'):
        raise BridgeError('Installed MoW mission does not match this transition')
    if running('mowas_2_ed.exe'):raise BridgeError('Close the MoW editor before the automatic game launch')
    desktop=GameDesktop(cfg,root)
    state={'stage':'starting','started_at_ns':time.time_ns(),'game_load_verified':False,'events':[]}
    log=Path(cfg['mow_log']) if cfg.get('mow_log') else Path(cfg.get('mow_progress',str(Path(cfg.get('mow',''))/'profiles/profile/game_progress.set'))).parents[2]/'log/game.log'
    baseline=log.read_bytes() if log.is_file() else b''
    state['log_baseline']={'path':str(log),'size':len(baseline),'sha256':digest(baseline),'head_sha256':digest(baseline[:1024])}
    pending['mow_launch']=state;automatic._record()
    def checkpoint(step):
        state['ui_stage']=step
        state['events'].append({'step':step,'at_ns':time.time_ns()});automatic._record()
        if progress:progress(step)
    def acknowledged():
        if automatic.collect_loaded() or automatic.collect_final():return True
        failure=engine_failure(automatic,cfg)
        if failure:raise BridgeError(failure)
        return False
    try:
        needs_restart=installation.get('requires_engine_restart') and running('mowas_2.exe')
        manual_restart=existing_fresh_engine(target,log) if needs_restart else None
        if needs_restart and not manual_restart:
            if acknowledged():
                state.update(stage='mission_loaded',game_load_verified=True);automatic._record();return state
            checkpoint('restart_for_changed_map')
            state['map_restart_menu_proof']=desktop.close_mow_menu();automatic._record()
            end=time.monotonic()+30
            while running('mowas_2.exe'):
                if time.monotonic()>=end:raise BridgeError('Close Men of War to clear cached map/difficulty resources, then retry this prepared battle')
                time.sleep(.5)
            state['map_cache_restart']=True;automatic._record()
        if not running('mowas_2.exe'):
            exe=Path(cfg['mow'])/'mowas_2.exe'
            if not exe.is_file():raise BridgeError('MoW executable is missing')
            process=subprocess.Popen([str(exe)],cwd=exe.parent)
            state.update(launch_method='direct_executable',process_id=process.pid)
            automatic._record()
        else:
            process=None;state['launch_method']='reuse_running_game';automatic._record()
        checkpoint('wait_for_engine_main_page' if process is not None else 'wait_for_game_window')
        end=time.monotonic()+120
        while not desktop.ready_window('mow') or (process is not None and not startup_log_ready(log,baseline,state['started_at_ns'])):
            if process is not None and process.poll() not in (None,0):
                raise BridgeError('MoW exited before its main window appeared (code '+str(process.returncode)+')')
            if time.monotonic()>=end:raise BridgeError('MoW main window did not appear within 120 seconds')
            time.sleep(1)
        if process is not None:
            # A new process reached its own main page: old engine resources
            # cannot survive. A failed close must never clear this receipt.
            (target/'.hmb-engine-restart.json').unlink(missing_ok=True)
            state['fresh_engine_resources_verified']=True
        if manual_restart:
            if existing_fresh_engine(target,log)!=manual_restart:
                raise BridgeError('MoW process or installed resources changed during restart verification')
            (target/'.hmb-engine-restart.json').unlink()
            state.update(fresh_engine_resources_verified=True,manual_restart_verification=manual_restart)
        state['stage']='navigating';automatic._record()
        if installation.get('map_slot'):
            from .map_bank import validate_installed_bank
            bank=validate_installed_bank(target)
            if installation['map_slot'] not in [s['mission_path'] for s in bank['slots']]:
                raise BridgeError('Requested map is not registered in the installed bank')
            desktop.navigate_mission(progress=checkpoint,acknowledged=acknowledged,mission_slot=installation['map_slot'],
                registered_slots=[s['mission_path'] for s in bank['slots']])
        else:desktop.navigate_mission(progress=checkpoint,acknowledged=acknowledged)
        verified=automatic.pending['status'] in ('mission_loaded','result_ready')
        state.update(stage='mission_loaded' if verified else 'waiting_ack',game_load_verified=verified,navigation_finished_at_ns=time.time_ns())
        automatic._record()
    except (OSError,BridgeError) as error:
        state.update(stage='stopped',error=str(error),failed_at_ns=time.time_ns());automatic._record()
        desktop.diagnose(error)
        raise
    finally:write_json(Path(pending['path'])/'mow-launch.json',state)
    return state


def engine_failure(automatic,cfg):
    """Detect a closed game or a new crash record without inspecting its UI."""
    from .launch_native import running
    pending=automatic.pending
    if not pending or pending['status'] not in ('ready','mission_loaded'):return None
    launch=pending.get('mow_launch',{})
    if not launch:return None
    baseline=launch.get('log_baseline')
    if baseline:
        path=Path(baseline['path'])
        try:
            if path.stat().st_mtime_ns>=launch['started_at_ns']:
                data=path.read_bytes();size=baseline['size']
                same=bool(size and len(data)>=size and (
                    digest(data[:size])==baseline['sha256'] if baseline.get('sha256')
                    else digest(data[:min(1024,size)])==baseline['head_sha256']))
                fresh=data[size:] if same else data
                if b'***************** Exception *****************' in fresh:
                    return 'Men of War crashed; see its game.log. No result is inferred from a crash.'
        except OSError:pass
    if not running('mowas_2.exe'):return 'Men of War is closed. The prepared battle is retained.'
    return None


def recover_acknowledgment(automatic,attempts=4):
    """Read-only recovery after Space was pressed while UI detection stopped."""
    pending=automatic.pending
    if not pending or pending['status']!='ready' or not pending.get('mow_launch'):return False
    for attempt in range(attempts):
        if automatic.collect_loaded() or automatic.collect_final():
            pending['mow_launch'].update(stage='mission_loaded',game_load_verified=True)
            pending.pop('driver_error',None);automatic._record()
            write_json(Path(pending['path'])/'mow-launch.json',pending['mow_launch']);return True
        if attempt+1<attempts:time.sleep(1)
    return False


def retry(automatic,cfg,root):
    """Explicit user retry, only after recognizing a menu (no mission running)."""
    pending=automatic.pending
    if not pending or pending['status']!='ready' or pending.get('strategic_result_applied') or pending.get('engine_load_verified'):
        raise BridgeError('Only an unacknowledged tactical load can be retried')
    previous=pending.get('mow_launch',{})
    if previous.get('stage') not in ('starting','navigating','waiting_ack','stopped','manual_wait','engine_failed'):
        raise BridgeError('No unfinished MoW launch to retry')
    from .desktop import GameDesktop
    from .launch_native import running
    if running('mowas_2.exe'):
        proof=GameDesktop(cfg,root).confirm_mow_menu()
    else:proof={'kind':'mow_process_closed','verified_at_ns':time.time_ns()}
    pending.setdefault('mow_launch_attempts',[]).append({**previous,'retry_preflight':proof})
    del pending['mow_launch'];pending.pop('driver_error',None);automatic._record()
    return start(automatic,cfg,root)
