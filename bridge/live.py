"""Direct live return adapter for the version-locked native HOI4 runtime."""
import json
import math
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from .core import BridgeError, read_json, write_json
from .native import NativeHOI


def fixed(value):
    return int((Decimal(str(value))*100000).to_integral_value(rounding=ROUND_HALF_EVEN))


def selector(b,retreats=None):
    provinces={str(b['province']):True};units={}
    for side in ('attacker','defender'):
        for d in b[side]['divisions']:
            units[d['id']]=True;provinces[str(d['province'])]=True
    for p in (retreats or {}).values():provinces[str(p)]=True
    return {'units':units,'provinces':provinces}


def build_plan(b,result,state,retreats=None,test_fixture=False):
    from .core import validate_result,tag
    from .save_import import vanilla_strength_from_manpower
    checked={**result,'evidence':{**result.get('evidence',{}),'kind':'mow_save'}} if test_fixture and result.get('evidence',{}).get('kind')=='test_fixture' else result
    validate_result(b,checked);retreats=retreats or {}
    if state['campaign_id']!=b['campaign_id']:raise BridgeError('Live campaign differs from exported battle')
    if state.get('flags',{}).get('hmb_'+b['id']) or state.get('flags',{}).get('hmb_pending_'+b['id']):
        raise BridgeError('This live result is already applied or pending')
    combat=state['combats'].get(b['combat_id'])
    if not combat or combat['province']!=b['province']:raise BridgeError('Selected combat is no longer present')
    if any(key!=b['combat_id'] and c['province']==b['province'] for key,c in state['combats'].items()):
        raise BridgeError('Another combat is active in the same province')
    plan=selector(b,retreats)
    plan['provinces']={p:True for p in state['provinces']}
    plan.update(battle_id=b['id'],campaign_id=b['campaign_id'],combat_id=b['combat_id'],
                winner=result['winner'],country=b[result['winner']]['country'],province=b['province'],
                before=state,targets={})
    tag(plan['country'])
    if state['provinces'][str(b['province'])]['controller']!=b['defender']['country']:
        raise BridgeError('Battle province changed controller')
    for side in ('attacker','defender'):
        expected={d['id'] for d in b[side]['divisions']}
        if set(combat[side])!=expected:raise BridgeError('Live combat participants changed')
        for loss in result['losses'][side]:
            d=b[side]['divisions'][loss['index']];current=state['units'].get(d['id'])
            if not current:raise BridgeError('Participating division missing')
            if (current['country'],current['owner'],current['logical_country'],current['province'],current['template_id'],current['manpower'])!=(d['country'],d['country'],d['country'],d['province'],int(d['template']['id'].split(':')[0]),d['manpower']):
                raise BridgeError('Live division identity, template or manpower changed: '+d['id'])
            normalized=vanilla_strength_from_manpower(d)
            valid_hp={fixed(d['strength_hp'])}
            if normalized is not None:valid_hp.add(fixed(normalized))
            if current['hp'] not in valid_hp or abs(current['org']-fixed(d['organization_points']))>1:
                raise BridgeError('Live division strength or organization changed: '+d['id'])
            if current['combat_count']!=1 or any(key!=b['combat_id'] and any(d['id'] in c[s] for s in ('attacker','defender')) for key,c in state['combats'].items()):
                raise BridgeError('Division participates in more than the selected combat')
            equipment={e['variant_id']:fixed(e['amount']) for e in d['equipment']}
            if {k:v['amount'] for k,v in current['equipment'].items()}!=equipment:
                raise BridgeError('Live equipment changed: '+d['id'])
            lost=loss['manpower_lost'];remaining=d['manpower']-lost
            if remaining<=0 or lost>d['manpower']*.25:raise BridgeError('Live import must preserve at least 75% manpower')
            target={'org':int((Decimal(current['org'])*(1-Decimal(str(loss.get('organization_loss_ratio',loss['loss_ratio']))))).to_integral_value(rounding=ROUND_HALF_EVEN)),
                    'manpower':remaining,'equipment':{},'manpower_values':{},'province':d['province'],
                    'loser':side!=result['winner']}
            values=current['manpower_values'];total=sum(v['amount'] for v in values.values())
            if total!=d['manpower']:raise BridgeError('Live manpower components do not sum to the snapshot')
            allocated={k:v['amount']*remaining//total for k,v in values.items()}
            order=sorted(values,key=lambda k:((values[k]['amount']*remaining)%total,-int(k)),reverse=True)
            for k in order[:remaining-sum(allocated.values())]:allocated[k]+=1
            target['manpower_values']={k:{'addr':values[k]['addr'],'before':values[k]['amount'],'value':v} for k,v in allocated.items()}
            eq_losses={e['variant_id']:fixed(e['amount_lost']) for e in result.get('equipment_losses',{}).get(side,[]) if e['index']==loss['index']}
            target['equipment']={k:{'addr':v['addr'],'before':v['amount'],'value':v['amount']-eq_losses.get(k,0)} for k,v in current['equipment'].items()}
            if side=='defender' and target['loser']:
                destination=retreats.get(d['id'])
                if not destination or str(destination) not in state['provinces']:raise BridgeError('Verified retreat destination required')
                if state['provinces'][str(destination)]['controller']!=d['country']:raise BridgeError('Retreat province is not friendly')
                if any(o['province']==destination and o['country']!=d['country'] for o in state['occupants'].values()):raise BridgeError('Retreat province contains hostile units')
                target['province']=destination
            if side=='attacker' and not target['loser']:
                target['province']=b['province']
            changed={**d,'manpower':remaining}
            target['hp']=fixed(vanilla_strength_from_manpower(changed)) if normalized is not None else None
            if target['hp'] is None:raise BridgeError('Template HP cannot be verified')
            plan['targets'][d['id']]=target
    return plan


def apply_session(session,retreats=None,test_fixture=False):
    from .core import Ledger,config,vanilla_data_compatible,archive_result_evidence
    from .geography import neighbors
    session=Path(session).resolve();b=read_json(session/'battle.json');result=read_json(session/'result.json')
    record=session/'live-return.json'
    if record.exists():raise BridgeError('Direct return already attempted; inspect its report instead of reapplying')
    if not vanilla_data_compatible(b.get('source_mods',[])):raise BridgeError('Live return requires the supported vanilla gameplay data')
    if not (test_fixture and result.get('evidence',{}).get('kind')=='test_fixture'):archive_result_evidence(result,session)
    client=LiveHOI();health=client.client.health()
    if not health['paused'] or health['date']!=b['snapshot_date']:raise BridgeError('Expected original paused battle date')
    ledger=Ledger(session/'ledger.sqlite')
    row=ledger.db.execute('SELECT status FROM battles WHERE id=?',(b['id'],)).fetchone()
    ledger.db.close()
    if not row or row[0]!='exported':raise BridgeError('Battle is not awaiting its first application')
    cfg=config();retreats=retreats or {};nearby={}
    if result['winner']=='attacker':
        for d in b['defender']['divisions']:
            nearby[d['id']]=neighbors(d['province'],cfg['hoi4'])
    select=selector(b,retreats)
    for values in nearby.values():
        select['provinces'].update({str(p):True for p in values})
    state=client.inspect(select)
    if state['hour']!=health['game_hour']:raise BridgeError('Live campaign advanced')
    if result['winner']=='attacker':
        for d in b['defender']['divisions']:
            choices=sorted(p for p in nearby[d['id']] if state['provinces'][str(p)]['controller']==d['country']
                and p!=b['province'] and not any(o['province']==p and o['country']!=d['country'] for o in state['occupants'].values()))
            if d['id'] not in retreats:
                if not choices:raise BridgeError('No safe friendly retreat destination')
                retreats[d['id']]=choices[0]
            if retreats[d['id']] not in choices:raise BridgeError('Unsafe/nonadjacent retreat destination')
    plan=build_plan(b,result,state,retreats,test_fixture)
    write_json(session/'live-plan.json',plan)
    report={'stage':'applying','battle_id':b['id'],'save_or_load_used':False,'test_fixture':test_fixture,'before':state,'retreats':retreats}
    write_json(record,report)
    ledger=Ledger(session/'ledger.sqlite')
    with ledger.db:
        changed=ledger.db.execute("UPDATE battles SET status='live_applying' WHERE id=? AND status='exported'",(b['id'],))
        if changed.rowcount!=1:
            ledger.db.close();raise BridgeError('Another worker already claimed this return')
    try:
        report['after']=client.apply(plan)
        after_health=client.client.health()
        if not after_health['paused'] or after_health['game_hour']!=health['game_hour']:raise BridgeError('Campaign advanced during live return')
        report.update(stage='verified',health_after=after_health)
        with ledger.db:ledger.db.execute("UPDATE battles SET status='applied',result=? WHERE id=? AND status='live_applying'",(json.dumps(report),b['id']))
    except Exception as error:
        report.update(stage='failed_requires_inspection',error=str(error))
        try:report['partial_state']=client.inspect(select)
        except Exception:pass
        with ledger.db:ledger.db.execute("UPDATE battles SET status='live_failed' WHERE id=?",(b['id'],))
        raise
    finally:
        write_json(record,report);ledger.db.close()
    return report


def lua(value):
    if value is None:return 'nil'
    if isinstance(value,bool):return 'true' if value else 'false'
    if isinstance(value,(int,float)):
        if not math.isfinite(value):raise BridgeError('Non-finite plan value')
        return str(value)
    if isinstance(value,str):return json.dumps(value,ensure_ascii=False)
    if isinstance(value,dict):return '{'+','.join('['+lua(str(k))+']='+lua(v) for k,v in value.items())+'}'
    raise BridgeError('Unsupported Lua plan type')


class LiveHOI:
    def __init__(self):
        self.client=NativeHOI()
        self.client.health()
        self.client.request('/lua',Path(__file__).with_name('live_runtime.lua').read_text(encoding='utf8'))

    def inspect(self,plan):
        response=self.client.request('/lua','return HMB_LIVE.json(HMB_LIVE.inspect('+lua(plan)+'))')
        return json.loads(response['result'])

    def cancel(self,plan):
        response=self.client.request('/lua','return HMB_LIVE.json(HMB_LIVE.cancel('+lua(plan)+'))',timeout=30)
        return json.loads(response['result'])

    def apply(self,plan):
        state=self.client.health()
        if not state['paused'] or state['game_hour']!=plan['before']['hour']:
            raise BridgeError('Campaign must remain paused at the preflight hour')
        response=self.client.request('/lua','return HMB_LIVE.json(HMB_LIVE.apply('+lua(plan)+'))',timeout=90)
        return json.loads(response['result'])


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--session')
    args=parser.parse_args()
    if args.session:print(json.dumps(apply_session(args.session),ensure_ascii=False,indent=2))
    else:
        plan={'units':{'1:51':True,'374:51':True},'provinces':{'142':True,'9039':True,'6117':True}}
        print(json.dumps(LiveHOI().inspect(plan),ensure_ascii=False,indent=2))
