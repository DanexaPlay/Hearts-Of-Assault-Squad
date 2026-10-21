"""One-hour engine continuation check of an already verified direct return."""
import argparse
import pathlib
import sys
import time
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from bridge.core import read_json,write_json,BridgeError
from bridge.live import LiveHOI


def main(session):
    session=pathlib.Path(session);plan=read_json(session/'live-plan.json');report=read_json(session/'live-return.json')
    if report['stage']!='verified':raise BridgeError('A verified direct return is required')
    client=LiveHOI();before=client.inspect(plan);health=client.client.health()
    if not health['paused'] or before['campaign_id']!=plan['campaign_id'] or before['hour']!=plan['before']['hour']:
        raise BridgeError('Test campaign changed before continuation check')
    result={'before':before,'before_health':health}
    # Pause at the next frame after the next hourly update. The native console
    # pause_in_hours command proved inconsistent across in-place test reloads.
    tick_timer=client.client.request('/lua',
        'local g=hoi4.read_u64(hoi4.base()+0x332F260); local h=hoi4.read_u32(g+1128); '
        'local id; id=hoi4.every(1,function() if hoi4.read_u32(g+1128)>=h+1 then '
        'hoi4.game_pause(1); hoi4.every_cancel(id) end end); return id')
    rescue=client.client.request('/lua','return hoi4.after(30000,function() hoi4.game_pause(1) end)')
    try:
        client.client.request('/lua','hoi4.game_set_speed(0); return hoi4.game_pause(0)')
        deadline=time.monotonic()+40
        while time.monotonic()<deadline:
            state=client.client.health()
            if state['paused'] and state['game_hour']>before['hour']:break
            time.sleep(.2)
        else:raise BridgeError('Automatic one-hour pause was not observed')
    finally:
        client.client.ensure_paused()
        if str(tick_timer.get('result','')).isdigit():client.client.request('/lua','return hoi4.every_cancel('+tick_timer['result']+')')
        if str(rescue.get('result','')).isdigit():client.client.request('/lua','return hoi4.every_cancel('+rescue['result']+')')
    after=client.inspect(plan);result['after']=after
    write_json(session/'live-tick.json',result)
    if after['hour']!=before['hour']+1:raise BridgeError('Continuation advanced more than one hour')
    if plan['combat_id'] in after['combats']:raise BridgeError('Resolved combat reappeared')
    for key,target in plan['targets'].items():
        actual=after['units'].get(key)
        if not actual or actual['province']!=target['province']:raise BridgeError('Division disappeared or changed province')
        if actual['manpower']<target['manpower'] or actual['combat_count']:
            raise BridgeError('Division suffered unexpected losses or resumed fighting')
        if actual['path_count'] and (not actual.get('path') or any(p['controller']!=actual['country'] for p in actual['path'].values())):
            raise BridgeError('Division received a new route outside friendly territory')
    if after['provinces'][str(plan['province'])]['controller']!=plan['country']:raise BridgeError('Province changed controller')
    result['verified']=True;write_json(session/'live-tick.json',result)
    print('PASS: both divisions survived one game hour; no combat or attack resumed; province control persisted. Friendly AI regrouping is allowed.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('session');args=parser.parse_args();main(args.session)
