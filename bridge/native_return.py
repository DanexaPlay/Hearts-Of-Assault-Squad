"""Prepare and verify a tactical return through the native HOI4 API."""
import time
from pathlib import Path
from .core import BridgeError, Ledger, read_json, write_json, config
from .native import NativeHOI
from .save_import import retreat_candidates


def wait_save(folder, name, timeout=100):
    deadline=time.monotonic()+timeout;last=None;stable=0
    while time.monotonic()<deadline:
        matches=[folder/(name+suffix) for suffix in ('.hoi4','_temp.hoi4') if (folder/(name+suffix)).is_file()]
        if matches:
            path=max(matches,key=lambda p:p.stat().st_mtime_ns)
            state=(str(path),path.stat().st_size,path.stat().st_mtime_ns)
            stable=stable+1 if state==last else 0;last=state
            if state[1]>1000 and stable>=3:return path
        time.sleep(1)
    raise BridgeError('Native save did not stabilize; command must not be repeated')


def prepare(session):
    session=Path(session).resolve();cfg=config();client=NativeHOI()
    b=read_json(session/'battle.json');result=read_json(session/'result.json')
    record=session/'native-return.json'
    previous=read_json(record) if record.exists() else None
    if previous and previous['stage'] not in ('preflight_requested','preflight_verified'):
        raise BridgeError('Native return already prepared or loaded; refusing another preparation')
    state=client.ensure_paused()
    if state.get('date')!=b['snapshot_date']:raise BridgeError('Campaign date changed')
    saves=Path(cfg['hoi4_user'])/'save games';name='HMB_preflight_'+b['id']
    if previous:
        report=previous
        if state['game_hour']!=report['before']['game_hour']:raise BridgeError('Campaign changed before preparation resumed')
    else:
        if list(saves.glob(name+'*.hoi4')):raise BridgeError('Preflight name already exists')
        report={'stage':'preflight_requested','battle_id':b['id'],'before':state}
        write_json(record,report)
        report['preflight_response']=client.request('/console','savegame '+name,timeout=65)
        write_json(record,report)
    fresh=wait_save(saves,name)
    from .hoi import verify_snapshot
    report['preflight']=verify_snapshot(b,fresh,require_clear_locations=False)
    report['stage']='preflight_verified';write_json(record,report)
    choices=retreat_candidates(b,fresh) if result['winner']=='attacker' else {}
    retreats={}
    for loss in result['losses']['defender']:
        if loss.get('retreat_required'):
            did=b['defender']['divisions'][loss['index']]['id']
            if not choices.get(did):raise BridgeError('No verified friendly retreat destination: '+did)
            retreats[did]=choices[did][0]
    report.update(retreat_candidates=choices,retreats=retreats)
    output=session/('HMB_return_'+b['id']+'.hoi4')
    ledger=Ledger(session/'ledger.sqlite')
    report['prepared']=ledger.prepare_save(b,result,fresh,output,retreats)
    ledger.db.close()
    report.update(stage='prepared',save_name=output.stem)
    write_json(record,report)
    publish(report,saves)
    print('Separate return save prepared:',output,flush=True)
    return report


def publish(report,saves):
    import shutil
    from .core import digest
    source=Path(report['prepared']['path']);destination=saves/source.name
    if destination.exists():
        if digest(destination.read_bytes())!=report['prepared']['output_sha256']:
            raise BridgeError('Return destination already exists with different content')
        return
    # Stage and validate in the project; only publish the final dedicated file.
    with source.open('rb') as incoming,destination.open('xb') as outgoing:
        shutil.copyfileobj(incoming,outgoing)
    if digest(destination.read_bytes())!=report['prepared']['output_sha256']:
        raise BridgeError('Published return save hash mismatch')


def load(session):
    session=Path(session).resolve();record=session/'native-return.json';report=read_json(record)
    if report['stage']!='prepared':raise BridgeError('No prepared native return awaits loading')
    publish(report,Path(config()['hoi4_user'])/'save games')
    client=NativeHOI();state=client.ensure_paused()
    if state['game_hour']!=report['before']['game_hour']:raise BridgeError('Campaign time changed before return')
    from .core import digest
    if digest(Path(report['prepared']['path']).read_bytes())!=report['prepared']['output_sha256']:
        raise BridgeError('Prepared save changed')
    # Persist before queuing the load. Never repeat a timed-out load request.
    report['stage']='load_requested';write_json(record,report)
    chunk='return hoi4.load_save('+__import__('json').dumps(report['save_name'])+')'
    report['load_response']=client.request('/lua',chunk,timeout=90)
    write_json(record,report)
    if report['load_response'].get('result')!='true':raise BridgeError('Native load failed')
    return verify(session)


def verify(session):
    session=Path(session).resolve();record=session/'native-return.json';report=read_json(record)
    if report['stage']!='load_requested' or report.get('load_response',{}).get('result')!='true':
        raise BridgeError('No acknowledged native load awaits verification')
    client=NativeHOI();deadline=time.monotonic()+120
    # The load call returns before the extension has processed session reset.
    while time.monotonic()<deadline:
        state=client.request('/health')
        if state.get('version')!=client.VERSION:raise BridgeError('Unexpected runtime after load')
        if state.get('session_active') is True:break
        time.sleep(1)
    else:raise BridgeError('Loaded campaign did not become active')
    after=client.ensure_paused()
    if after['game_hour']!=report['before']['game_hour']:raise BridgeError('Unexpected date after return load')
    saves=Path(config()['hoi4_user'])/'save games';name='HMB_verified_'+report['battle_id']
    if not (report.get('verification_save_requested') or report.get('verification_save_response')):
        if list(saves.glob(name+'*.hoi4')):raise BridgeError('Verification save already exists')
        report['verification_save_requested']=True;write_json(record,report)
        report['verification_save_response']=client.request('/console','savegame '+name,timeout=65)
        write_json(record,report)
    fresh=wait_save(saves,name)
    from .hoi import save_text
    from .geography import controllers
    b=read_json(session/'battle.json');result=read_json(session/'result.json')
    _,text=save_text(fresh)
    expected=b[result['winner']]['country'] if result['winner']=='attacker' else b['defender']['country']
    if controllers(text,config()['hoi4']).get(b['province'])!=expected:raise BridgeError('Province control failed verification')
    ledger=Ledger(session/'ledger.sqlite')
    report['verification']=ledger.acknowledge_save(report['battle_id'],fresh);ledger.db.close()
    report.update(stage='verified',health_after=client.health(),province_controller=expected)
    write_json(record,report)
    write_json(session/'loaded_save_verification.json',report['verification'])
    print('Native return verified; HOI4 remains paused.',flush=True)
    return report


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','load','verify']);parser.add_argument('session')
    args=parser.parse_args()
    {'prepare':prepare,'load':load,'verify':verify}[args.action](args.session)
