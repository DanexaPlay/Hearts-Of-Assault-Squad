"""User-run two-combat button test. Never launches MoW or imports losses."""
import time,uuid
from pathlib import Path
from bridge.core import ROOT,BridgeError,write_json
from bridge.launch_native import connect
from bridge.requests import RequestWatcher
from bridge.transition import AutomaticTransfer,worker_lock,select_requested_combat
from bridge.hoi import read_campaign


def main():
    with worker_lock(ROOT/'sessions/automatic'):
        cfg,client=connect()
        if client.request('/lua','return type(HMB_SELECTION)..":"..type(hoi4.get_effect("hmb_capture_combat_selection"))')['result']!='table:function':
            raise BridgeError('Restart HOI4 to load the updated selection effect')
        client.request('/lua','HMB_SELECTION.ready=0; return "checking effect routing"')
        routed=client.request('/console','eval_effect hmb_selection_ready = yes')
        if 'error' in routed.get('result','').lower() or client.request('/lua','return tostring(HMB_SELECTION.ready)')['result']!='1':
            raise BridgeError('HOI4 has not loaded the updated button effects. Restart the game, not only this window')
        watcher=RequestWatcher(Path(cfg['hoi4_user'])/'logs/game.log')
        root=ROOT/'native_trial/evidence'/('combat_selection_'+uuid.uuid4().hex);root.mkdir(parents=True)
        records=[]
        print('Selection trial ready. Start TWO land combats, pause, open combat A and press the MoW button. Then open combat B and press it again. MoW will not be launched; no losses will be imported.',flush=True)
        while len(records)<2:
            for line in watcher.poll():
                transfer=AutomaticTransfer(cfg,root/'requests'/uuid.uuid4().hex)
                transfer.request(line)
                if transfer.pending['request'].get('selection')!='native_v1':raise BridgeError('Old button detected. Restart HOI4 with the updated mod')
                client.capture(transfer)
                end=time.monotonic()+120;snapshot=None
                while time.monotonic()<end:
                    snapshot=transfer.find_fresh_snapshot()
                    if snapshot:break
                    time.sleep(.5)
                if not snapshot:raise BridgeError('No stable selection test snapshot')
                campaign=read_campaign(snapshot);selected=transfer.pending['selected_combat']
                if campaign['campaign_id']!=selected['campaign_id']:raise BridgeError('Campaign changed during selection test')
                country=selected['country']
                involved=[c for c in campaign['combats'] if any(d['country']==country for side in ('attacker','defender') for d in c[side])]
                if len(involved)<2:raise BridgeError('This test requires at least TWO simultaneous player land combats')
                combat=select_requested_combat(campaign,transfer.pending['request'])
                if any(r['selection']['combat']==combat['combat_id'] for r in records):
                    print('Same combat selected again. Open the OTHER combat window and press its button.',flush=True);continue
                records.append({'selection':selected,'snapshot':str(snapshot),'simultaneous_player_combats':len(involved)})
                write_json(root/'selection-verification.json',{'stage':'one_selected' if len(records)<2 else 'verified','records':records,'mow_launched':False,'losses_imported':False})
                print('Selected '+combat['combat_id']+' at province '+str(combat['province'])+'; '+str(len(involved))+' simultaneous combats verified.',flush=True)
            time.sleep(.5)
        print('PASS: two different combat windows selected their own battles. No MoW launch or losses imported.\nEvidence: '+str(root),flush=True)


if __name__=='__main__':
    try:main()
    except (BridgeError,OSError) as error:raise SystemExit('Combat selection trial stopped: '+str(error))
