"""Restore only the known paused test campaign after preserving its live state."""
import shutil,time,uuid
from pathlib import Path
from bridge.core import ROOT,BridgeError,config,read_json,write_json,digest
from bridge.native import NativeHOI
from bridge.live import LiveHOI,selector


def main():
    cfg=config();source=ROOT/'sessions/automatic/6cee77b81d4443e392ca01a22101329d'
    battle=read_json(source/'battle.json');api=NativeHOI();before=api.health()
    state=LiveHOI().inspect(selector(battle))
    if not before['paused'] or state['campaign_id']!=battle['campaign_id']:
        raise BridgeError('Only the known paused test campaign can be restored')
    root=ROOT/'native_trial/evidence'/('full_cycle_setup_'+uuid.uuid4().hex)
    root.mkdir(parents=True)
    saves=Path(cfg['hoi4_user'])/'save games';old=saves/'GER_1936_01_01_16_temp.hoi4'
    if not old.is_file():raise BridgeError('Original test save is missing')
    shutil.copy2(old,root/old.name)
    write_json(root/'setup.json',{'stage':'preserving_current_test','before':before,'live_before':state,
        'original_test_save_sha256':digest(old.read_bytes())})
    name='HMB_before_cycle_'+uuid.uuid4().hex[:12]
    api.request('/console','savegame '+name,timeout=65)
    end=time.monotonic()+90;previous=None
    while time.monotonic()<end:
        found=[p for p in saves.glob(name+'*.hoi4') if p.is_file()]
        signature=[(str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in found]
        if signature and signature==previous:
            for p in found:shutil.copy2(p,root/p.name)
            break
        previous=signature;time.sleep(1)
    else:raise BridgeError('Backup save did not stabilize; test not restored')
    if api.request('/lua','return hoi4.load_save("GER_1936_01_01_16_temp")',timeout=90).get('result')!='true':
        raise BridgeError('Test save load did not succeed')
    time.sleep(3);end=time.monotonic()+120
    while time.monotonic()<end:
        if api.request('/health').get('session_active') is True:break
        time.sleep(1)
    else:raise BridgeError('Test campaign did not finish loading')
    health=api.ensure_paused();api.request('/lua','HMB_LIVE=nil; return true')
    after=LiveHOI().inspect(selector(battle))
    if after['campaign_id']!=battle['campaign_id'] or battle['combat_id'] not in after['combats']:
        raise BridgeError('Expected original test combat not found')
    write_json(root/'setup.json',{'stage':'ready','backup_save_name':name,'before':before,'live_before':state,
        'health_after':health,'live_after':after,'restored_test_save':'GER_1936_01_01_16_temp',
        'original_test_save_sha256':digest(old.read_bytes())})
    print('Ready: original paused test combat restored. Backup:',name,'\nEvidence:',root)


if __name__=='__main__':main()
