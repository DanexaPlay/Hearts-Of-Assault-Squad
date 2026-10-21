"""Explicit user recovery: preserve current campaign, retire a partial return.

Never applies a result or changes units. Keeps the pending in-game flag as a
permanent block against replaying the old battle. Requires a matching campaign.
"""
import json,shutil,time,uuid
from pathlib import Path
from .core import ROOT,BridgeError,Ledger,read_json,write_json,digest
from .live import LiveHOI,lua


def validate_abandon(transfer):
    pending=transfer.pending
    if not pending or pending.get('status') not in ('result_ready','return_abandoned') or pending.get('strategic_result_applied'):
        raise BridgeError('No partially applied return awaiting explicit resolution')
    if pending['status']=='return_abandoned' and pending.get('partial_return_resolution',{}).get('mode')!='keep_current_campaign':
        raise BridgeError('Unknown partial-return resolution')
    session=Path(pending['path']);report=read_json(session/'live-return.json')
    if report.get('stage')!='failed_requires_inspection':raise BridgeError('Return is not a verified failed attempt')
    return session,report,read_json(session/'live-plan.json')


def logical_state(value):
    # Fresh loading rebuilds engine pointers. All gameplay values, selected
    # combat, flags, paths, occupants and the hour must still match exactly.
    if isinstance(value,dict):
        return {key:logical_state(item) for key,item in value.items()
                if key not in ('addr','variant','gs','base')}
    return value


def classify_loaded_campaign(plan,current):
    if current.get('campaign_id')!=plan['campaign_id']:
        raise BridgeError('Loaded campaign has a different campaign ID')
    flags=current.get('flags',{})
    if flags.get('hmb_'+plan['battle_id']):
        raise BridgeError('Loaded campaign already marks this result as applied; inspection is required')
    if flags.get('hmb_pending_'+plan['battle_id']):return 'partial_return_present'
    before=plan.get('before')
    if before and logical_state(current)==logical_state(before):return 'original_pre_return_snapshot_restored'
    raise BridgeError('No pending return flag and loaded state does not match the original pre-return snapshot')


def preserve_current(transfer,cfg):
    session,report,plan=validate_abandon(transfer);client=LiveHOI();api=client.client
    health=api.ensure_paused();current=client.inspect(plan)
    if current['campaign_id']!=plan['campaign_id'] or current['hour']!=health['game_hour']:
        raise BridgeError('Load the current campaign that contains this partial return')
    loaded_kind=classify_loaded_campaign(plan,current)
    if loaded_kind=='original_pre_return_snapshot_restored':print('Original pre-return snapshot verified. The old attempt will be retired without applying its result.',flush=True)
    existing=[]
    for record in (session/'recovery').glob('*/backup.json'):
        item=read_json(record)
        if item.get('stage')=='backup_requested' and logical_state(item.get('current_state'))==logical_state(current):
            existing.append((record,item))
    if existing:
        record,evidence=existing[-1];folder=record.parent;name=evidence['native_save_name']
    else:
        folder=session/'recovery'/uuid.uuid4().hex;folder.mkdir(parents=True)
        name='HMB_before_partial_return_resolution_'+folder.name
        evidence={'stage':'backup_requested','campaign_id':current['campaign_id'],'game_hour':current['hour'],
                  'native_save_name':name,'current_state':current,'health_before':health,'loaded_state_kind':loaded_kind}
        write_json(folder/'backup.json',evidence)
        api.request('/console','savegame '+name,timeout=65)
    saves=Path(cfg['hoi4_user'])/'save games';deadline=time.monotonic()+15
    stable={}
    while time.monotonic()<deadline:
        # Saving temporarily marks the engine session inactive. Poll only the
        # read-only endpoint; never issue the save command a second time.
        after=api.request('/health')
        if not after.get('session_active'):
            time.sleep(.3);continue
        if after.get('version')!=api.VERSION or not after.get('paused') or after.get('game_hour')!=health['game_hour']:
            raise BridgeError('Campaign changed during recovery backup')
        for source in (saves/(name+'.hoi4'),saves/(name+'_temp.hoi4')):
            if not source.is_file():continue
            data=source.read_bytes();sha=digest(data)
            if stable.get(str(source))!=sha:stable[str(source)]=sha;continue
            from .hoi import save_text
            import re
            _,text=save_text(source)
            def header(key):
                match=re.search(r'(?m)^'+key+r'=("[^"\n]*"|[^\s\n]+)',text)
                return match[1].strip('"') if match else None
            if header('game_unique_id')!=current['campaign_id'] or header('date')!=health.get('date'):
                raise BridgeError('Recovery backup belongs to another campaign or date; old return remains locked')
            if digest(source.read_bytes())!=sha:raise BridgeError('Recovery backup changed while being verified')
            backup=folder/'current-campaign.hoi4';backup.write_bytes(data)
            evidence.update(stage='backup_verified',backup_path=str(backup.resolve()),backup_sha256=sha,health_after=after)
            write_json(folder/'backup.json',evidence);return evidence
        time.sleep(.3)
    raise BridgeError('Named recovery backup did not become stable; old return remains locked')


def abandon_partial(transfer,backup):
    session,report,plan=validate_abandon(transfer)
    source=Path(backup.get('backup_path',''))
    if (backup.get('stage')!='backup_verified' or backup.get('campaign_id')!=plan['campaign_id'] or
            not source.is_file() or digest(source.read_bytes())!=backup.get('backup_sha256')):
        raise BridgeError('Verified current-campaign backup is required')
    if not source.resolve().is_relative_to((session/'recovery').resolve()):raise BridgeError('Recovery backup is outside this session')
    if not transfer.active_file.exists() or Path(read_json(transfer.active_file)['session']).resolve()!=session.resolve():
        raise BridgeError('Another tactical session is active')
    write_json(source.parent/'transition-before-resolution.json',transfer.pending)
    ledger=Ledger(session/'ledger.sqlite')
    try:
        with ledger.db:
            # A crash after this commit but before the active-pointer removal
            # must be resumable without ever replaying tactical losses.
            changed=ledger.db.execute("UPDATE battles SET status='abandoned_partial' WHERE id=? AND status IN ('live_failed','abandoned_partial')",(plan['battle_id'],))
            if changed.rowcount!=1:raise BridgeError('Partial return ledger is not awaiting recovery')
    finally:ledger.db.close()
    transfer.pending.update(status='return_abandoned',native_return_stage='abandoned_partial',
        partial_return_resolution={'mode':'keep_current_campaign','backup':backup,'additional_losses_applied':False})
    transfer._record();transfer.active_file.unlink();transfer.pending=None
    return {'stage':'old partial result retired; current campaign preserved','backup':backup,'additional_losses_applied':False}


def finalize_completed_partial(transfer,cfg):
    """Finish only a fully applied, exactly verified result; never replay it."""
    session,report,plan=validate_abandon(transfer)
    if 'Strength/organization verification failed' not in report.get('error',''):
        raise BridgeError('This recovery only handles native strength clamping')
    if not transfer.active_file.exists() or Path(read_json(transfer.active_file)['session']).resolve()!=session.resolve():
        raise BridgeError('Another tactical session is active')
    intent=session/'strength-finalization.json'
    if intent.exists():raise BridgeError('Receipt finalization already attempted; inspect its evidence')
    client=LiveHOI();health=client.client.health();current=client.inspect(plan)
    if not health['paused'] or health['game_hour']!=plan['before']['hour']:
        raise BridgeError('Campaign must remain paused at the original return hour')
    if logical_state(current)!=logical_state(report.get('partial_state')):
        raise BridgeError('Campaign changed since the failed return; inspection required')
    limits=json.loads(client.client.request('/lua','return HMB_LIVE.json(HMB_LIVE.verify_result('+lua(plan)+',HMB_LIVE.inspect('+lua(plan)+')))')['result'])
    ledger=Ledger(session/'ledger.sqlite')
    try:
        row=ledger.db.execute('SELECT status FROM battles WHERE id=?',(plan['battle_id'],)).fetchone()
        if not row or row[0]!='live_failed':raise BridgeError('Return ledger is not awaiting inspection')
        backup=preserve_current(transfer,cfg)
        current=client.inspect(plan)
        if logical_state(current)!=logical_state(report['partial_state']):raise BridgeError('Campaign changed during backup')
        evidence={'stage':'finalizing_receipt','backup':backup,'strength_limits':limits,'additional_losses_applied':False}
        write_json(session/'live-return-before-strength-fix.json',report)
        write_json(intent,evidence)
        after=json.loads(client.client.request('/lua','return HMB_LIVE.json(HMB_LIVE.finalize_verified('+lua(plan)+','+lua(current)+'))',timeout=30)['result'])
        end=client.client.health()
        if not end['paused'] or end['game_hour']!=health['game_hour']:raise BridgeError('Campaign advanced during receipt finalization')
        report.update(stage='verified',after=after,health_after=end,recovery=evidence)
        with ledger.db:
            changed=ledger.db.execute("UPDATE battles SET status='applied',result=? WHERE id=? AND status='live_failed'",(json.dumps(report),plan['battle_id']))
            if changed.rowcount!=1:raise BridgeError('Return ledger changed during finalization')
        write_json(session/'live-return.json',report)
        evidence['stage']='verified';write_json(intent,evidence)
        transfer.pending.update(native_return_stage='verified',strategic_result_applied=True,
            return_verification={'kind':'live_state','report':str(session/'live-return.json'),'save_or_load_used':False,'receipt_only_recovery':True})
        transfer._record()
        return evidence
    finally:ledger.db.close()


def main():
    from .launch_native import connect
    from .transition import AutomaticTransfer,worker_lock
    from .core import config
    cfg=config();root=ROOT/'sessions/automatic'
    with worker_lock(root):
        transfer=AutomaticTransfer(cfg,root)
        if transfer.pending and transfer.pending.get('status')=='return_abandoned':
            backup=transfer.pending['partial_return_resolution']['backup']
        else:
            cfg,_=connect()
            backup=preserve_current(transfer,cfg)
        result=abandon_partial(transfer,backup)
        write_json(ROOT/'runtime/partial-return-resolution.json',result)
        print('Current campaign backed up. Old partial result retired without additional losses. Start_Native_Bridge.cmd can now be started.',flush=True)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--keep-current',action='store_true');args=parser.parse_args()
    if not args.keep_current:parser.error('Explicit --keep-current confirmation is required')
    try:main()
    except (OSError,BridgeError) as error:raise SystemExit('Partial return remains locked: '+str(error))
