"""Prepare a separate text save with exact losses and cancelled combat orders."""
import re,math,os,uuid
from pathlib import Path
from .core import BridgeError,digest,write_json,validate_battle,validate_result,vanilla_data_compatible
from .hoi import save_text,read_campaign,identifier,verify_snapshot
from .clausewitz import parse
from .gem import block_at

def replace_spans(text,changes):
    changes=sorted(changes,reverse=True)
    previous=len(text)+1
    for start,end,value in changes:
        if start<0 or end<start or end>previous: raise BridgeError('Overlapping save changes')
        text=text[:start]+value+text[end:]; previous=start
    return text

def prepare_save(b,result,current_save,output,retreats=None,test_fixture=False):
    validate_battle(b)
    if test_fixture and result.get('evidence',{}).get('kind')=='test_fixture':
        # Explicit engine-load fixture, never reported as a real tactical import.
        checked={**result,'evidence':{**result['evidence'],'kind':'mow_save'}}
    else: checked=result
    validate_result(b,checked) # exact division edits do not require province-wide damage
    if b.get('source')!='hoi4_text_save': raise BridgeError('Save import requires a real exported battle')
    verify_snapshot(b,current_save,require_clear_locations=False)
    raw,text=save_text(current_save); flag='hmb_'+b['id']
    if not vanilla_data_compatible(b.get('source_mods',[])): raise BridgeError('Save territory import currently requires the vanilla map')
    from .geography import controllers
    from .core import config
    control=controllers(text,config()['hoi4'])
    if control.get(b['province'])!=b['defender']['country']:
        raise BridgeError('Battle province controller changed or cannot be verified')
    if flag in text: raise BridgeError('This tactical result has already been applied')
    output=Path(output)
    if output.resolve()==Path(current_save).resolve() or output.exists(): raise BridgeError('Use a new save filename; original saves must not be overwritten')
    retreats=retreats or {}; edits=[]; report=[]
    units={}
    for match in re.finditer(r'(?m)^\t\t\tdivision=\{',text):
        begin=text.index('{',match.start()); block=block_at(text,begin)
        node=parse('division='+block).one('division')
        units[identifier(node.all('id')[0])]=(begin,block,node)
    for side in ('attacker','defender'):
        for loss in result['losses'][side]:
            d=b[side]['divisions'][loss['index']]; begin,block,node=units[d['id']]
            local='division='+block; changes=[]
            ratio=loss['loss_ratio']; org=loss.get('organization_loss_ratio',ratio)
            if not 0<=ratio<=0.25 and result.get('loss_policy'): raise BridgeError('New policy must preserve at least 75% manpower')
            for field,multiplier in [('strength',1-ratio),('organisation',1-org)]:
                n=node.one(field); value=max(0,float(n.value)*multiplier)
                changes.append((n.start,n.end,field+'='+format(value,'.5f')))
            manpower_group=node.one('army_manpower').one('army_manpower_value')
            values=[n.one('value') for n in manpower_group.walk('value') if n.value is None and n.get('value') is not None]
            target=d['manpower']-loss['manpower_lost']
            scaled=[float(n.value)*(1-ratio) for n in values]
            allocated=[math.floor(v) for v in scaled]
            for i in sorted(range(len(values)),key=lambda i:scaled[i]-allocated[i],reverse=True)[:target-sum(allocated)]: allocated[i]+=1
            for n,value in zip(values,allocated): changes.append((n.start,n.end,'value='+str(max(0,value))))
            specific={e['variant_id']:e['amount_lost'] for e in result.get('equipment_losses',{}).get(side,[]) if e['index']==loss['index']}
            for group in node.all('equipment'):
                for eq in group.all('equipment'):
                    amount=eq.one('amount'); current=float(amount.value); vid=identifier(eq.one('id'))
                    lost=specific.get(vid,0) if 'equipment_losses' in result else current*ratio
                    changes.append((amount.start,amount.end,'amount='+format(max(0,current-lost),'.5f')))
            destination=d['province']; retreat_kind=None
            if side!=result['winner']:
                for field in ('path','movement_progress','move_priority','strategic_redeployment'):
                    for n in node.all(field): changes.append((n.start,n.end,''))
                if side=='defender':
                    destination=retreats.get(d['id'])
                    if not destination: raise BridgeError('Defending division needs a verified friendly retreat province: '+d['id'])
                    verify_retreat(text,b,d,destination,current_save)
                    n=node.one('location'); changes.append((n.start,n.end,'location='+str(destination)))
                    retreat_kind='moved_to_friendly_neighbor'
                else: retreat_kind='attack_cancelled_at_origin'
            edited=replace_spans(local,changes)
            edits.append((begin,begin+len(block),edited[len('division='):]))
            report.append({'side':side,'id':d['id'],'manpower_before':d['manpower'],'manpower_after':target,'organization_after':float(node.get('organisation'))*(1-org),'province_after':destination,'retreat':retreat_kind})
    combats=[]
    for match in re.finditer(r'(?m)^\tland_combat=\{',text):
        begin=text.index('{',match.start()); block=block_at(text,begin)
        node=parse('land_combat='+block).one('land_combat')
        if identifier(node.one('id'))==b['combat_id']: combats.append((match.start(),begin+len(block),''))
    if len(combats)!=1: raise BridgeError('Cannot identify unique combat to resolve')
    edits.extend(combats)
    flags=re.search(r'(?m)^flags=\{',text)
    if not flags: raise BridgeError('Cannot locate global flags')
    begin=text.index('{',flags.start())
    edits.append((begin+1,begin+1,'\n\t'+flag+'={ value=1 date="'+b['snapshot_date']+'" }\n'))
    if result['winner']=='attacker':
        provinces=re.search(r'(?m)^provinces=\{',text); begin=text.index('{',provinces.start()); block=block_at(text,begin)
        match=re.search(r'(?m)^\t'+str(b['province'])+r'=\{',block)
        if match:
            pbegin=begin+block.index('{',match.start()); pblock=block_at(text,pbegin)
            node=parse('province='+pblock).one('province'); controllers=node.all('controller')
            if controllers:
                n=controllers[0]; offset=pbegin-len('province=')
                edits.append((offset+n.start,offset+n.end,'controller="'+b['attacker']['country']+'"'))
            else: edits.append((pbegin+1,pbegin+1,'controller="'+b['attacker']['country']+'" '))
        else: edits.append((begin+1,begin+1,'\n\t'+str(b['province'])+'={ controller="'+b['attacker']['country']+'" }\n'))
    patched=replace_spans(text,edits)
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_name(output.name+'.'+uuid.uuid4().hex+'.tmp')
    payload=b'HOI4txt'+patched.encode('utf8')
    try:
        temporary.write_bytes(payload); check=read_campaign(temporary)
        if any(c['combat_id']==b['combat_id'] for c in check['combats']): raise BridgeError('Combat remained in prepared save')
        if len(check['divisions'])!=len(units): raise BridgeError('A division disappeared while preparing save')
        for item in report:
            d=check['divisions'][item['id']]
            if d['manpower']!=item['manpower_after'] or any(e['amount']<0 for e in d['equipment']): raise BridgeError('Prepared loss values failed verification')
            if d['province']!=item['province_after'] or abs(d['organization_points']-item['organization_after'])>0.0001: raise BridgeError('Prepared retreat/organization failed verification')
        # Rename refuses an existing destination on Windows, preserving every original.
        if output.exists(): raise BridgeError('Output save appeared during preparation')
        os.rename(temporary,output)
    finally:
        if temporary.exists(): temporary.unlink()
    evidence={'battle_id':b['id'],'combat_id':b['combat_id'],'campaign_id':b['campaign_id'],'snapshot_date':b['snapshot_date'],'test_fixture':test_fixture,'source_sha256':digest(raw),'output_sha256':digest(payload),'path':str(output.resolve()),'changes':report,'expected_divisions':{i['id']:check['divisions'][i['id']] for i in report},'stage':'prepared; engine reload not yet verified'}
    write_json(output.with_suffix('.verification.json'),evidence)
    return evidence

def retreat_candidates(b,current_save):
    from .geography import neighbors,controllers
    from .core import config
    if not vanilla_data_compatible(b.get('source_mods',[])): raise BridgeError('Retreat selection requires the vanilla map')
    _,text=save_text(current_save); campaign=read_campaign(current_save)
    control=controllers(text,config()['hoi4']); nearby={}; choices={}
    for division in b['defender']['divisions']:
        province=division['province']
        if province not in nearby: nearby[province]=neighbors(province,config()['hoi4'])
        hostile={d['province'] for d in campaign['divisions'].values() if d['country']!=division['country']}
        choices[division['id']]=sorted(p for p in nearby[province] if control.get(p)==division['country'] and p not in hostile and p!=b['province'])
    return choices

def verify_retreat(text,b,division,destination,current_save):
    from .geography import neighbors,controllers
    from .core import config
    if destination not in neighbors(division['province'],config()['hoi4']): raise BridgeError('Retreat destination is not adjacent land')
    if controllers(text,config()['hoi4']).get(destination)!=division['country']: raise BridgeError('Retreat destination is not controlled by division country')
    from .hoi import read_campaign
    # The same paused snapshot was already verified; do not move into hostile troops.
    campaign=read_campaign(current_save)
    if any(d['province']==destination and d['country']!=division['country'] for d in campaign['divisions'].values()):
        raise BridgeError('Retreat destination contains troops from another country')

def verify_loaded_save(report,path):
    """A fresh paused game save must contain the prepared strategic outcome."""
    raw,text=save_text(path); campaign=read_campaign(path)
    if campaign['campaign_id']!=report['campaign_id'] or campaign['date']!=report['snapshot_date'] or campaign['speed']!='0':
        raise BridgeError('Verify a fresh paused save immediately after loading the prepared campaign')
    if not re.search(r'(?m)^\s*hmb_'+re.escape(report['battle_id'])+r'\s*=\s*\{',text):
        raise BridgeError('Applied battle flag is absent from the game save')
    if any(c['combat_id']==report['combat_id'] for c in campaign['combats']): raise BridgeError('Resolved combat is still active')
    recalculated_strength={}
    for did,expected in report['expected_divisions'].items():
        actual=campaign['divisions'].get(did)
        if not actual: raise BridgeError('Participating division disappeared: '+did)
        for key in ('province','manpower','country'):
            if actual[key]!=expected[key]: raise BridgeError('Loaded division changed '+key+': '+did)
        if abs(actual['organization_points']-expected['organization_points'])>0.001: raise BridgeError('Loaded division changed organization_points: '+did)
        if abs(actual['strength_hp']-expected['strength_hp'])>0.001:
            normalized=vanilla_strength_from_manpower(expected)
            if normalized is None or abs(actual['strength_hp']-normalized)>0.001:
                raise BridgeError('Loaded division changed strength_hp: '+did)
            recalculated_strength[did]={'prepared':expected['strength_hp'],'engine':actual['strength_hp'],'expected_from_template_and_manpower':normalized}
        actual_gear={e['variant_id']:e['amount'] for e in actual['equipment']}
        expected_gear={e['variant_id']:e['amount'] for e in expected['equipment']}
        if actual_gear.keys()!=expected_gear.keys() or any(abs(actual_gear[k]-v)>0.001 for k,v in expected_gear.items()):
            raise BridgeError('Loaded equipment differs from prepared losses: '+did)
    if digest(raw)==report['output_sha256']:
        raise BridgeError('This is the prepared file itself; select a new save made by HOI4 after loading')
    return {'path':str(Path(path).resolve()),'sha256':digest(raw),'battle_id':report['battle_id'],'strength_recalculated_by_engine':recalculated_strength,'stage':'fresh game save matches prepared outcome; engine origin supplied by user'}

def vanilla_strength_from_manpower(division):
    """Observed HOI4 1.19.3 load normalization; verify the exact computed value.

    Unsupported templates or additional HP modifiers fail the comparison rather
    than permitting a broad numerical tolerance.
    """
    components=division.get('template',{}).get('components',[])
    required=division.get('required_manpower',0)
    if not components or required<=0: return None
    from .formations import unit_definitions
    from .core import config
    definitions=unit_definitions(config()['hoi4'])
    if any(c['type'] not in definitions for c in components): return None
    from decimal import Decimal, ROUND_FLOOR
    maximum=sum(Decimal(str(definitions[c['type']]['max_strength'])) for c in components)
    # The engine uses 1e-5 fixed point: truncate the manpower ratio BEFORE
    # multiplying by template HP, then truncate HP to the same precision.
    ratio=(int(division['manpower'])*100000)//int(required)
    return float((maximum*ratio).to_integral_value(rounding=ROUND_FLOOR)/100000)
