"""Explicitly abandon an exited, unfinished tactical session. No HOI4 writes."""
import time
from pathlib import Path
from .core import ROOT,BridgeError,Ledger,config,read_json,write_json
from .transition import AutomaticTransfer,worker_lock


def cancel(automatic,proof):
    pending=automatic.pending
    if not pending:raise BridgeError('No unfinished tactical battle to cancel')
    if pending['status'] not in ('waiting_snapshot','ready','mission_loaded','failed','cancelling','cancelled'):
        raise BridgeError('A completed tactical result must be processed, not cancelled')
    if pending.get('strategic_result_applied') or pending.get('native_return_stage'):
        raise BridgeError('Strategic return already started; cancellation requires inspection')
    if proof.get('kind') not in ('mow_process_closed','recognized_mow_menu'):
        raise BridgeError('Exit from the old MoW mission must be verified before cancelling')
    session=Path(pending['path'])
    for name in ('result.json','live-plan.json','live-return.json','native-return.json'):
        if (session/name).exists():raise BridgeError('Result or return evidence exists; cancellation refused: '+name)
    ledger=None;bid=pending.get('battle_id')
    try:
        if (session/'ledger.sqlite').exists():
            if not bid:raise BridgeError('Cannot identify the battle ledger')
            ledger=Ledger(session/'ledger.sqlite')
            row=ledger.db.execute('SELECT status FROM battles WHERE id=?',(bid,)).fetchone()
            if not row or row[0] not in ('exported','cancelled'):
                raise BridgeError('Battle ledger no longer permits cancellation')
        elif bid:raise BridgeError('Battle ledger is missing; cancellation refused')
        pending.update(status='cancelling',cancellation={'reason':'explicit_user_cancellation',
            'verified_scene_exit':proof,'at_ns':time.time_ns(),'hoi4_modified':False,'losses_imported':False})
        automatic._record()
        if ledger:
            with ledger.db:
                ledger.db.execute("UPDATE battles SET status='cancelled' WHERE id=? AND status='exported'",(bid,))
        pending['status']='cancelled';automatic._record()
        write_json(session/'cancellation.json',pending['cancellation'])
        automatic.active_file.unlink();automatic.pending=None
        return pending['cancellation']
    finally:
        if ledger:ledger.db.close()


def verified_cancel(automatic,cfg):
    from .launch_native import running
    if not automatic.pending:raise BridgeError('No unfinished tactical battle to cancel')
    if running('mowas_2.exe'):
        from .desktop import GameDesktop
        proof=GameDesktop(cfg,ROOT).confirm_mow_menu(restore_focus=True)
    else:proof={'kind':'mow_process_closed','verified_at_ns':time.time_ns()}
    # A finished autosave may have appeared while the worker was stopped.
    # Try both stable reads after confirming scene exit. Never discard a result.
    for attempt in range(2):
        result=automatic.collect_final()
        if result:raise BridgeError('The tactical battle has a final result. Restart the bridge to transfer it instead of cancelling.')
        if attempt==0:time.sleep(1)
    return cancel(automatic,proof)


def main(restart=False):
    cfg=config()
    with worker_lock(ROOT/'sessions/automatic'):
        automatic=AutomaticTransfer(cfg,ROOT/'sessions/automatic')
        verified_cancel(automatic,cfg)
        print('Unfinished tactical battle cancelled and archived. HOI4 unchanged; no losses imported.',flush=True)
    if restart:
        from .launch_native import main as launch
        launch()


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--restart',action='store_true');args=parser.parse_args()
    try:main(args.restart)
    except (OSError,BridgeError) as error:raise SystemExit('Cancellation stopped: '+str(error))
