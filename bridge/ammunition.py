"""Scale native reserve ammunition without replacing weapons or personal gear."""
import json,math,re,zipfile
from pathlib import Path
from .archives import open_archive
from .core import BridgeError

def supply_ratio(division):
    # The named text-save field stores percentage points, not a 0..1 fraction.
    # In particular 0.5 means half a percent, not fifty percent.
    raw=division.get('supply_raw')
    if raw is None:return None
    try:value=float(raw)
    except (ValueError,TypeError):raise BridgeError('Invalid saved division supply percentage')
    if not math.isfinite(value) or value<0:raise BridgeError('Invalid saved division supply percentage')
    return min(1,value/100)

def ammunition_items(text,vehicle=False):
    from .gem import blocks
    roots=list(blocks(text))
    if len(roots)!=1:raise BridgeError('Native inventory source must have one root')
    pattern=r'\{extender\s+"inventory"' if vehicle else r'\{inventory\b'
    inventories=[block for block in blocks(roots[0][1:-1]) if re.match(pattern,block,re.I)]
    return read_reserve_items(inventories)

def read_reserve_items(inventories):
    found={}
    for inventory in inventories:
        for match in re.finditer(r'\{item\s+((?:"[^"\r\n]*"\s*)+)(\d+)?',inventory):
            words=[word for part in re.findall(r'"([^"\r\n]*)"',match[1]) for word in part.split()]
            category='ammo' if 'ammo' in words or any(w.startswith('bullet') for w in words) else 'grenade' if 'grenade' in words else None
            if category is None:continue
            identity=[w for w in words if w not in ('ammo','grenade')]+[category]
            if len(identity)<2:raise BridgeError('Incomplete native ammunition identity')
            key=tuple(identity);found[key]=found.get(key,0)+int(match[2] or 1)
    return [{'identity':list(key),'native_reserve':amount} for key,amount in found.items() if amount>0]

def audit_ammunition(roster,text):
    """Match generated actors to runtime UIDs before checking saved reserves."""
    from .gem import block_at
    uids={};inventories={}
    for match in re.finditer(r'\{(?:Entity|Human) "[^"\r\n]+" (0x[0-9a-fA-F]+)',text):
        entity=block_at(text,match.start());mid=re.search(r'\{MID (\d+)\}',entity)
        if mid:uids[int(mid[1])]=int(match[1],16)
    for match in re.finditer(r'\{Inventory (0x[0-9a-fA-F]+)',text):
        inventories[int(match[1],16)]={tuple(item['identity']):item['native_reserve'] for item in read_reserve_items([block_at(text,match.start())])}
    checked=[]
    for actor in roster:
        expected=actor.get('ammunition',{}).get('items',[])
        if not expected:continue
        uid=uids.get(actor['mid'])
        if uid is None or uid not in inventories:raise BridgeError('Missing ammunition inventory for MID '+str(actor['mid']))
        actual=inventories[uid]
        for item in expected:
            count=actual.get(tuple(item['identity']),0)
            if count!=item['reserve']:raise BridgeError('Ammunition mismatch for MID '+str(actor['mid'])+' '+str(item['identity'])+': expected '+str(item['reserve'])+', got '+str(count))
        checked.append(actor['mid'])
    return {'stage':'native reserve quantities verified','actor_mids':checked,'actors_checked':len(checked)}

def scaled_reserves(items,supply,equipment,minimum=.20):
    if not isinstance(minimum,(int,float)) or not math.isfinite(minimum) or not 0<minimum<=1:raise BridgeError('Ammo reserve floor must be in (0, 1]')
    for value in (supply,equipment):
        if value is not None and (not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=1):raise BridgeError('Invalid ammunition readiness ratio')
    factor=max(minimum,(1 if supply is None else supply)*(1 if equipment is None else equipment))
    return factor,[{**item,'reserve':max(1,math.ceil(item['native_reserve']*factor))} for item in items]

def build_ammunition(b,cfg,roster,dest):
    from .gem import inline_breed_includes
    from .formations import catalog
    from .objectives import node,scalar
    entities,_=catalog(cfg);cache={};actions=[];report=[]
    with open_archive(Path(cfg['mow'])/'resource/gamelogic.pak') as game:
        for actor in roster:
            vehicle=actor['kind']=='vehicle';key=actor.get('entity') if vehicle else actor.get('breed')
            if (vehicle,key) not in cache:
                if vehicle:
                    archive,member=entities[key]
                    with open_archive(archive) as archive_file:text=archive_file.read(member).decode('utf-8-sig')
                else:
                    local=Path(dest)/('resource/set/breed/'+key+'.set')
                    member='set/breed/'+key+'.set'
                    text=local.read_text(encoding='utf8') if local.is_file() else inline_breed_includes(game.read(member).decode('utf-8-sig'),member,game)
                cache[vehicle,key]=ammunition_items(text,vehicle)
            division=b[actor['side']]['divisions'][actor['division_index']]
            supply=supply_ratio(division);equipment=actor.get('equipment_readiness_ratio')
            factor,items=scaled_reserves(cache[vehicle,key],supply,equipment,cfg.get('minimum_ammunition_ratio',.20))
            actor['ammunition']={'supply_ratio':supply,'equipment_ratio':equipment,'factor':factor,'items':items,
                'loaded_weapons':'native ready rounds retained; scaling applies to reserve ammunition'}
            changed=[item for item in items if item['reserve']!=item['native_reserve']]
            if changed:
                tag='hmb_ammo_'+str(actor['mid']);actor['ammunition_tag']=tag
                for item in changed:
                    descriptor=node('item',*[json.dumps(word) for word in item['identity']])
                    selector=node('selector',scalar('ignore_captured_by_user',0),scalar('tag',tag))
                    actions += [node('"inventory"',selector,scalar('action','remove'),descriptor,scalar('amount',1000000)),
                                node('"inventory"',selector,scalar('action','add'),descriptor,scalar('amount',item['reserve']))]
            report.append({'mid':actor['mid'],'side':actor['side'],'division_index':actor['division_index'],
                'source':key,**actor['ammunition'],'status':'native reserves found' if items else 'no explicit reserve ammunition; native inventory retained'})
    return {'actions':actions,'report':{'actors':report,'minimum_ratio':cfg.get('minimum_ammunition_ratio',.20),
        'missing_data':'unknown supply/equipment each use neutral multiplier 1 and remain explicitly unknown',
        'scope':'explicit native inventory reserves and grenades; loaded weapon rounds and inherited macro-only stores are unchanged',
        'stage':'generated; reserve quantities require native save verification'}}
