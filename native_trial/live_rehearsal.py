"""Explicit test setup only: replay an archived real result in the test save.

The load below resets the TEST scenario. The direct return itself neither saves
nor loads the game. This script is not used by the production watcher.
"""
import json
import pathlib
import shutil
import sys
import time
import uuid
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from bridge.core import read_json,write_json,Ledger,BridgeError
from bridge.live import LiveHOI,selector,apply_session
from bridge.native import NativeHOI

ROOT=pathlib.Path(__file__).resolve().parents[1]
SOURCE=ROOT/'sessions/automatic/6cee77b81d4443e392ca01a22101329d'


def main(defeat_fixture=False):
    b=read_json(SOURCE/'battle.json');client=LiveHOI();state=client.inspect(selector(b))
    if state['campaign_id']!=b['campaign_id'] or not client.client.health()['paused']:
        raise BridgeError('Only the paused known TEST campaign may be reset')
    session=ROOT/'sessions/live-return-rehearsal'/uuid.uuid4().hex;session.mkdir(parents=True)
    for name in ('battle.json','result.json'):shutil.copy2(SOURCE/name,session/name)
    if defeat_fixture:
        from bridge.core import calculate_result
        roster=read_json(SOURCE/'roster.json')
        result=calculate_result(b,roster,'defender',[a['mid'] for a in roster if a['side']=='attacker'],
            {'kind':'test_fixture','description':'Synthetic attacker defeat; no new MoW battle played'})
        write_json(session/'result.json',result)
    ledger=Ledger(session/'ledger.sqlite');ledger.register(b);ledger.db.close()
    write_json(session/'rehearsal.json',{'kind':'real_result_replay_on_restored_test_campaign',
        'source_session':str(SOURCE),'not_a_new_mow_battle':True,'synthetic_defeat_fixture':defeat_fixture,'state_before_test_reset':state})
    print('Rehearsal:',session,flush=True)
    response=client.client.request('/lua','return hoi4.load_save("GER_1936_01_01_16_temp")',timeout=90)
    if response.get('result')!='true':raise BridgeError('Test reset failed')
    time.sleep(3)
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        health=client.client.request('/health')
        if health.get('session_active') is True:break
        time.sleep(1)
    else:raise BridgeError('Test campaign did not become active')
    client.client.ensure_paused()
    client.client.request('/lua','HMB_LIVE=nil; return "test runtime reset"')
    print('Applying direct result; no save/load inside apply_session...',flush=True)
    report=apply_session(session,test_fixture=defeat_fixture)
    print(json.dumps({'stage':report['stage'],'session':str(session),'units':report['after']['units'],
                      'combats':report['after']['combats']},ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--defeat-fixture',action='store_true');args=parser.parse_args()
    main(args.defeat_fixture)
