"""Read real HOI4 text-save divisions and active land combats.

The observed 1.19.2 save contains countries/<tag>/division and land_combat
records. Each division's manpower comes from army_manpower_value, not HP.
Only small record blocks are parsed, avoiding a full save AST in memory.
"""
import bisect,csv,json,math,re,uuid,zipfile
from pathlib import Path
from .clausewitz import parse
from .gem import blocks,block_at
from .core import BridgeError,digest,config,vanilla_data_compatible

def save_text(path):
    path=Path(path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z: raw=z.read('gamestate')
    else: raw=path.read_bytes()
    if not raw.startswith(b'HOI4txt'): raise BridgeError('Use a HOI4txt non-Ironman save; binary decoding is not implemented')
    return raw,raw[7:].decode('utf-8-sig')

def identifier(node):
    return str(node.get('id'))+':'+str(node.get('type'))

def line_positions(text,prefix,start=0,end=None):
    """Literal line prefixes avoid regex scanning every character of 60MB saves."""
    end=len(text) if end is None else end
    if start==0 and text.startswith(prefix):yield 0
    needle='\n'+prefix;pos=start-1 if start else 0
    while True:
        pos=text.find(needle,max(0,pos),end)
        if pos<0:return
        yield pos+1
        pos+=len(needle)

def read_campaign(path,*,combat_units_only=False):
    raw,text=save_text(path)
    templates={}; variants={}
    def section(name):
        pos=next(line_positions(text,name+'={'),None)
        return parse(name+'='+block_at(text,text.index('{',pos))).one(name) if pos is not None else None
    template_root=section('division_templates')
    if template_root:
        for node in template_root.all('division_template'):
            components=[]
            for group in ('regiments','support'):
                for entries in node.all(group):
                    for component in entries.children:
                        components.append({'type':component.key,'group':group,'x':int(component.get('x',0)),'y':int(component.get('y',0))})
            tid=identifier(node.one('id'))
            templates[tid]={'id':tid,'name':node.get('name',tid),'country':node.get('country'),'components':components}
    equipment_root=section('equipments')
    if equipment_root:
        def inspect(node,model):
            ids=node.all('id')
            if ids and ids[0].get('type')=='70':
                vid=identifier(ids[0]); modules={}
                for group in node.all('modules'):
                    modules.update({n.key:n.value for n in group.children if n.key})
                variants[vid]={'id':vid,'model':model,'name':node.get('name',model),'creator':node.get('creator'),'modules':modules}
            for child in node.children:
                if child.value is None and child.key not in ('id','modules'): inspect(child,model)
        for model in equipment_root.children: inspect(model,model.key)
    country_pos=next(line_positions(text,'countries={'),None)
    if country_pos is None: raise BridgeError('No countries section')
    country_start=text.index('{',country_pos)
    country_block=block_at(text,country_start)
    country_end=country_start+len(country_block)
    starts=[(country_start+m.start(),m[1]) for m in re.finditer(r'(?m)^\t([A-Z][A-Z0-9]{2})=\{',country_block)]
    positions=[p for p,_ in starts]; countries={}
    for i,(pos,country) in enumerate(starts):
        end=starts[i+1][0] if i+1<len(starts) else country_end
        segment=text[pos:end]
        party_pos=segment.find('ruling_party=')
        while party_pos>0 and (segment[party_pos-1].isalnum() or segment[party_pos-1]=='_'):
            party_pos=segment.find('ruling_party=',party_pos+1)
        party=re.compile(r'ruling_party="?([a-z_]+)"?').match(segment,party_pos) if party_pos>=0 else None
        countries[country]={'ideology':party[1] if party else None}
        seq_pos=next(line_positions(segment,'\t\t\thmb_request_seq='),None)
        request_seq=re.compile(r'\t\t\thmb_request_seq=(\d+)(?:\.0+)?\s*$',re.M).match(segment,seq_pos) if seq_pos is not None else None
        if request_seq: countries[country]['hmb_request_seq']=int(request_seq[1])
    combat_nodes=[];involved=set()
    for pos in line_positions(text,'\tland_combat={'):
        node=parse('land_combat='+block_at(text,text.index('{',pos))).one('land_combat')
        combat_nodes.append(node)
        for side in ('attacker','defender'):
            side_nodes=node.all(side)
            if len(side_nodes)!=1:raise BridgeError('Unsupported combat side structure')
            involved.update(identifier(n) for n in side_nodes[0].all('unit'))
    records=[];identities=set();locations=set()
    for pos in line_positions(text,'\t\t\tdivision={',country_start,country_end):
        begin=text.index('{',pos)
        block=block_at(text,begin)
        if combat_units_only:
            # Read only direct identity/location fields first. Never discard a
            # co-located idle division: export_combat needs it for its guard.
            ident=re.search(r'(?m)^\t{4}id=\{',block)
            location=re.search(r'(?m)^\t{4}location=(\d+)\s*$',block)
            if not ident or not location:raise BridgeError('Unsupported division header layout')
            did=identifier(parse('id='+block_at(block,block.index('{',ident.start()))).one('id'))
            if did in identities:raise BridgeError('Duplicate division ID')
            identities.add(did);loc=int(location[1])
            if did in involved:locations.add(loc)
            records.append((pos,block,did,loc))
        else:records.append((pos,block,None,None))
    if combat_units_only and not involved.issubset(identities):raise BridgeError('Combat contains an unknown division')
    divisions={}
    for pos,block,header_id,loc in records:
        if combat_units_only and header_id not in involved and loc not in locations:continue
        node=parse('division='+block).one('division')
        ids=node.all('id')
        if not ids: raise BridgeError('Division without ID')
        did=identifier(ids[0]); owner=starts[bisect.bisect_right(positions,pos)-1][1]
        manpower_node=node.one('army_manpower')
        def manpower(key):
            return sum(float(n.get('value')) for n in manpower_node.one(key).walk('value') if n.value is None and n.get('value') is not None)
        current=manpower('army_manpower_value'); maximum=manpower('army_manpower_need')
        if not math.isfinite(current) or current<0: raise BridgeError('Invalid manpower in save')
        names=node.all('division_name')
        name=names[0].get('override',did) if names else did
        equipment=[]
        for eq_group in node.all('equipment'):
            for eq in eq_group.all('equipment'):
                equipment.append({'variant_id':identifier(eq.one('id')),'amount':float(eq.get('amount',0))})
        divisions[did]={'id':did,'country':owner,'logical_country':node.get('logical_country'),
            'name':name,'province':int(node.get('location')),'manpower':round(current),
            'required_manpower':round(maximum),'strength_hp':float(node.get('strength',0)),
            'organization_points':float(node.get('organisation',0)),
            'supply_raw':node.get('army_current_supply_ratio'),'equipment':equipment}
        template_ids=node.all('division_template_id')
        if template_ids:
            tid=identifier(template_ids[0])
            if tid not in templates: raise BridgeError('Unknown division template '+tid)
            divisions[did]['template']=templates[tid]
            for eq in equipment:
                if eq['variant_id'] not in variants: raise BridgeError('Unknown equipment variant '+eq['variant_id'])
                eq['variant']=variants[eq['variant_id']]
    combats=[]
    for node in combat_nodes:
        combat={'combat_id':identifier(node.one('id')),'province':int(node.get('location'))}
        for side in ('attacker','defender'):
            side_nodes=node.all(side)
            if len(side_nodes)!=1: raise BridgeError('Unsupported combat side structure')
            ids=[identifier(n) for n in side_nodes[0].all('unit')]
            if any(i not in divisions for i in ids): raise BridgeError('Combat contains an unknown division')
            combat[side]=[divisions[i] for i in ids]
        combats.append(combat)
    def header(key):
        pos=next(line_positions(text,key+'='),None)
        m=re.compile(re.escape(key)+r'=("[^"\n]*"|[^\s\n]+)').match(text,pos) if pos is not None else None
        return m[1].strip('"') if m else None
    mods_pos=next(line_positions(text,'mods={'),None)
    # Vanilla 1.19.3 omits this header; the observed modded 1.19.2 save lists mods.
    mods=[]
    if mods_pos is not None:
        mods_node=parse('mods='+block_at(text,text.index('{',mods_pos))).one('mods')
        mods=[n.value for n in mods_node.children if n.value is not None]
    from .weather import read_weather
    weather=read_weather(text,[c['province'] for c in combats])
    return {'source_path':str(Path(path).resolve()),'source_sha256':digest(raw),
        'date':header('date'),'campaign_id':header('game_unique_id'),'speed':header('speed'),'difficulty':header('difficulty') or 'normal',
        'version':header('version'),'mods':mods,'player_country':header('player'),
        'countries':countries,'templates':templates,'equipment_variants':variants,'divisions':divisions,'combats':combats,'weather':weather}

def vanilla_metadata(campaign,province,game_dir):
    """Resolve terrain/state only when the save explicitly has no active mods."""
    if not vanilla_data_compatible(campaign.get('mods')): raise BridgeError('Save has mods or unknown mod metadata; supply terrain/state manually')
    base=Path(game_dir)
    with (base/'map/definition.csv').open(encoding='utf-8-sig',newline='') as f:
        matching=[row for row in csv.reader(f,delimiter=';') if row and row[0]==str(province)]
    if len(matching)!=1 or matching[0][4]!='land': raise BridgeError('Cannot resolve a land province')
    terrain=matching[0][6]; states=[];victory_value=0
    for path in (base/'history/states').glob('*.txt'):
        text=path.read_text(encoding='utf-8-sig')
        group=re.search(r'\bprovinces\s*=\s*\{([^}]+)\}',text)
        if group and str(province) in group[1].split():
            state_id=re.search(r'\bid\s*=\s*(\d+)',text)
            if state_id: states.append(int(state_id[1]))
            for values in re.findall(r'\bvictory_points\s*=\s*\{([^}]+)\}',text):
                numbers=re.sub(r'#[^\n]*','',values).split()
                for i in range(0,len(numbers)-1,2):
                    if numbers[i]==str(province):victory_value=max(victory_value,int(numbers[i+1]))
    if len(states)!=1: raise BridgeError('Cannot resolve a unique state')
    from .weather import resolve_weather
    tactical_terrain='urban' if victory_value>=5 else terrain
    return {'state':states[0],'terrain':tactical_terrain,'base_terrain':terrain,'victory_point_value':victory_value,'weather':resolve_weather(campaign,province,game_dir),
        'source':'installed vanilla map definition and state history; major victory-point cities use urban tactical maps'}

def export_combat(campaign,combat_id,state,terrain,river=False):
    matches=[c for c in campaign['combats'] if c['combat_id']==combat_id]
    if len(matches)!=1: raise BridgeError('Select one existing combat ID')
    if campaign['speed']!='0': raise BridgeError('Save was made without strategic pause')
    combat=matches[0]
    b={'schema':1,'id':uuid.uuid4().hex,'province':combat['province'],'state':state,
       'weather':campaign.get('weather',{}).get('provinces',{}).get(str(combat['province']),{'known':False}),
       'terrain':terrain,'river_crossing':river,'war_confirmed':True,'paused_confirmed':True,
       'source':'hoi4_text_save','source_path':campaign['source_path'],
       'source_sha256':campaign['source_sha256'],'campaign_id':campaign['campaign_id'],
       'snapshot_date':campaign['date'],'combat_id':combat_id,'difficulty':campaign.get('difficulty','normal'),
       'source_mods':campaign.get('mods',[]),'source_version':campaign.get('version'),
       'loss_policy':config().get('loss_policy',{'max_manpower_loss_ratio':0.25,'defeat_org_damage_ratio':0.90,'defeat_min_loss_ratio':0.02,'winner_org_damage_ratio':0.20}),
       'metadata_source':'terrain and state supplied by player; mod map support not automatic'}
    exact=True
    for side in ('attacker','defender'):
        divs=combat[side]; tags={d['country'] for d in divs}
        if len(tags)!=1 or not divs: raise BridgeError('First adapter requires one country on each side')
        country=next(iter(tags)); ideology=campaign['countries'][country]['ideology']
        if not ideology: raise BridgeError('Cannot read current ruling ideology for '+country)
        if any(d['manpower']<=0 for d in divs): raise BridgeError('A participating division has zero manpower')
        b[side]={'country':country,'ideology':ideology,'divisions':divs}
        involved={d['id'] for d in divs}; locations={d['province'] for d in divs}
        exact &= not any(d['country']==country and d['province'] in locations and d['id'] not in involved for d in campaign['divisions'].values())
    b['all_divisions_in_locations_confirmed']=bool(exact)
    player=campaign.get('player_country')
    b['player_country']=player
    b['player_side']='defender' if player==b['defender']['country'] else 'attacker'
    return b

def verify_snapshot(b,current_save,require_clear_locations=True):
    current=read_campaign(current_save)
    if current['speed']!='0' or current['date']!=b['snapshot_date'] or current['campaign_id']!=b['campaign_id']:
        raise BridgeError('Campaign, date or pause changed; do not apply this tactical result')
    if current.get('mods',[])!=b.get('source_mods',[]):
        raise BridgeError('Active mods changed after export')
    if b.get('source_version') and current.get('version')!=b['source_version']:
        raise BridgeError('Game version changed after export')
    combats=[c for c in current['combats'] if c['combat_id']==b['combat_id']]
    if len(combats)!=1: raise BridgeError('Selected strategic battle is no longer present')
    for side in ('attacker','defender'):
        expected={d['id'] for d in b[side]['divisions']}
        if {d['id'] for d in combats[0][side]}!=expected:
            raise BridgeError('Participants changed after export')
        for division in b[side]['divisions']:
            if current['divisions'].get(division['id'])!=division:
                raise BridgeError('Division state changed after export: '+division['id'])
        locations={d['province'] for d in b[side]['divisions']}
        if require_clear_locations and any(d['country']==b[side]['country'] and d['province'] in locations and d['id'] not in expected for d in current['divisions'].values()):
            raise BridgeError('Additional divisions appeared in the damage locations')
    return {'path':current['source_path'],'sha256':current['source_sha256'],'date':current['date'],'campaign_id':current['campaign_id']}
