"""GEM text blocks based on installed AS2 missions; never pretend JSON is a mission."""
import json,re,zipfile, shutil,math,posixpath
from pathlib import Path
from .archives import open_archive,archive_session
from .core import BridgeError,make_roster,choose_map,write_json,digest,calculate_result,resolve_country,config
from .mission_paths import mission_path,assign_mission_path

def blocks(text):
    """Yield outer blocks with balanced braces, ignoring braces inside quotes."""
    start=None; depth=0; quote=False; escape=False
    for i,c in enumerate(text):
        if escape: escape=False; continue
        if c=='\\' and quote: escape=True; continue
        if c=='"': quote=not quote
        if quote: continue
        if c=='{':
            if depth==0: start=i
            depth+=1
        elif c=='}':
            depth-=1
            if depth<0: raise BridgeError('Malformed GEM block')
            if depth==0: yield text[start:i+1]
    if depth or quote: raise BridgeError('Unclosed GEM block')

# C-level scanning skips long numeric/whitespace runs. Quoted strings are
# consumed as one token, so braces and escaped quotes in names stay harmless.
_BLOCK_TOKEN=re.compile(r'"(?:\\[\s\S]|[^"\\])*"|[{}]|"')

def block_at(text,start):
    if text[start]!='{': raise BridgeError('Block must start with an opening brace')
    depth=0
    for token in _BLOCK_TOKEN.finditer(text,start):
        value=token[0]
        if value=='"':raise BridgeError('Unclosed block')
        if value[0]=='"':continue
        if value=='{':depth+=1
        else:
            depth-=1
            if depth==0:return text[start:token.end()]
    raise BridgeError('Unclosed block')


def inline_breed_includes(text,source,archive,visited=()):
    """Keep native local macros when moving a breed into the mod's folder."""
    if source in visited: raise BridgeError('Cyclic native breed include: '+source)
    def replace(match):
        name=posixpath.normpath(posixpath.join(posixpath.dirname(source),match[1]))
        if not name.startswith('set/breed/') or name not in archive.namelist():
            raise BridgeError('Missing native breed dependency: '+name)
        content=archive.read(name).decode('utf-8-sig')
        return inline_breed_includes(content,name,archive,visited+(source,))
    return re.sub(r'\(include\s+"([^"\r\n]+)"\s*\)',replace,text)

def formation_positions(roster,spawn,bounds,spacing=140,vehicle_spacing=500):
    """Keep the complete formation inside the native pathing rectangle.

    Linked crew share their vehicle position instead of expanding the grid.
    """
    x0,y0,x1,y1=bounds; positions={}
    for player in (0,1):
        actors=[a for a in roster if a['player']==player and not a.get('parent_mid')]
        vehicles=[a for a in actors if a.get('kind')=='vehicle']; foot=[a for a in actors if a.get('kind')!='vehicle']
        groups=[]
        for group,cell,max_columns in [(foot,spacing,8),(vehicles,vehicle_spacing,4)]:
            if not group: continue
            columns=min(max_columns,max(1,math.ceil(math.sqrt(len(group)))))
            rows=math.ceil(len(group)/columns)
            groups.append((group,cell,columns,(columns-1)*cell,(rows-1)*cell))
        width=max((g[3] for g in groups),default=0)
        gap=vehicle_spacing if len(groups)>1 else 0
        height=sum(g[4] for g in groups)+gap
        margin=150
        if width>x1-x0-2*margin or height>y1-y0-2*margin:
            raise BridgeError('Complete force cannot fit safely inside this map')
        cx=min(x1-margin-width/2,max(x0+margin+width/2,spawn[player][0]))
        cy=min(y1-margin-height/2,max(y0+margin+height/2,spawn[player][1]))
        bottom=cy-height/2
        for group,cell,columns,group_width,group_height in groups:
            for i,a in enumerate(group):
                positions[a['mid']]=(cx-group_width/2+(i%columns)*cell,bottom+(i//columns)*cell)
            bottom+=group_height+gap
    for a in roster:
        if a.get('parent_mid'): positions[a['mid']]=positions[a['parent_mid']]
    return positions

def campaign_menu(b,cfg,dest,archive):
    """Native AS2 folder discovery metadata, based on shipped interface.set files.

    Menu visibility and saving in the regular game still need an engine test.
    """
    side=b.get('player_side','attacker')
    faction=resolve_country(b[side]['country'],b[side]['ideology'],cfg)
    if cfg.get('preinstalled_map_slots',False):faction='ger'
    source={'ger':'02_ger-skirmish','rus':'04_rus-skirmish','usa':'01_usa-skirmish','eng':'03_eng-skirmish','jap':'05_jap-skirmish'}[faction]
    virtual=mission_path(b);mission_name=virtual.rsplit('/',1)[1]
    campaign=dest/'resource/map/single/hmb'; mission=campaign/mission_name
    (campaign/'interface.set').write_text('{location {side '+faction+'} {appid 244450}}',encoding='utf8')
    (mission/'interface.set').write_text('{location {level 0} {level_set 1}}',encoding='utf8')
    with open_archive(archive) as z:
        for name in ('background.dds','medal_big.dds'):
            native='map/single/'+source+'/'+name
            if native in z.namelist(): (campaign/name).write_bytes(z.read(native))
    localization=dest/'localization/mission/single/hmb'; localization.mkdir(parents=True,exist_ok=True)
    (localization/'campaign.lng').write_text('{tags {"title" "HOI4"} {"name" "HOI4 — Men of War"}}',encoding='utf8')
    (localization/(mission_name+'.lng')).write_text('{tags {"name" "'+b['attacker']['country']+' против '+b['defender']['country']+'"} {"name_big" "Тактическое сражение HOI4"} {"date" "'+b.get('snapshot_date','')+'"} {"place" "Провинция '+str(b['province'])+'"} {"outro_completed" "Победа"} {"outro_failed" "Поражение"} {"hmb_preparation" "Подготовка — расставьте войска"} {"hmb_clock" "Время сражения"} {"hmb_points_goal" "Захватывайте точки: победа при '+str(cfg.get('capture_score_to_win',100))+' очках или уничтожении противника. По таймеру побеждает сторона с большим счётом; ничья — обороняющийся."}}',encoding='utf8')
    if cfg.get('preinstalled_map_slots',False):
        label=localization/(mission_name+'.lng')
        text=label.read_text(encoding='utf8')
        label.write_text(text.replace(b['attacker']['country']+' против '+b['defender']['country'],b['map_source'].rsplit('/',1)[1]),encoding='utf8')

def generate(b,cfg,output):
    with archive_session():return _generate(b,cfg,output)


def _generate(b,cfg,output):
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    formation_report=[]
    if all(d.get('template') for side in ('attacker','defender') for d in b[side]['divisions']):
        from .formations import build_roster
        roster,formation_report=build_roster(b,cfg)
    else:
        if b.get('source')=='hoi4_text_save': raise BridgeError('Re-export this old snapshot to obtain full battalion composition')
        roster=make_roster(b,cfg)
    map_name,warning=choose_map(b['terrain'],b.get('river_crossing',False),cfg,b.get('weather'))
    archive=Path(cfg['mow'])/'resource/map.pak'
    # Complete map slots are registered before engine startup. Each terrain
    # keeps its immutable virtual path while subsequent rosters are replaced.
    if cfg.get('preinstalled_map_slots',False):
        from .mission_paths import map_slot
        b.update(map_source=map_name,mission_path=map_slot(map_name));virtual=mission_path(b)
    elif cfg.get('unique_mission_paths',False):virtual=assign_mission_path(b)
    else:
        b['mission_path']='single/hmb/battle';virtual=mission_path(b)
    dest=output/'mow_mod'; mission_dir=dest/('resource/map/'+virtual)
    mission_dir.mkdir(parents=True,exist_ok=True)
    prefix='map/'+map_name+'/'
    points=[]
    from .difficulty import install_profiles
    with open_archive(Path(cfg['mow'])/'resource/gamelogic.pak') as g:
        difficulty=install_profiles(b,dest,g)
    with open_archive(archive) as z:
        if prefix+"battle_zones.mi" in z.namelist():
            native=z.read(prefix+"battle_zones.mi").decode("utf8")
            entries=[]
            for match in re.finditer(r'\{Entity "flag_point_(\d+)"',native):
                entity=block_at(native,match.start())
                pos=re.search(r"\{Position ([^}]+)\}",entity)
                if pos: entries.append((int(match[1]),[float(v) for v in pos[1].split()[:2]]))
            points=[pos for _,pos in sorted(entries)]
        matches=[n for n in z.namelist() if n.startswith(prefix) and not n.endswith('/')]
        if not matches: raise BridgeError('Selected map is absent from installed game')
        for n in matches:
            rel=n[len(prefix):]
            if rel.endswith('.mi') or rel=='map.info': continue
            target=mission_dir/rel
            if not target.resolve().is_relative_to(mission_dir.resolve()): raise BridgeError('Unsafe map archive member')
            target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(z.read(n))
        map_text=z.read(prefix+'map').decode('utf8',errors='replace')
        # Use documented multiplayer spawn points, rather than guessing map bounds.
        spawn=[]
        if prefix+'combat.mi' in z.namelist():
            src=z.read(prefix+'combat.mi').decode('utf8')
            for match in re.finditer(r'\{Entity "map_point"[^\n]*',src):
                entity=next(blocks(src[match.start():]))
                if 'SpawnPoint' in entity:
                    pos=re.search(r'\{Position ([^}]+)\}',entity)
                    spawn.append([float(v) for v in pos[1].split()[:2]])
        if len(spawn)<2:
            # Campaign terrain remains unchanged; coordinates need editor verification.
            pather=re.search(r'\{pather ([^}]+)\}',map_text)
            if not pather: raise BridgeError('No spawn points or navigable rectangle')
            x0,y0,x1,y1=map(float,pather[1].split())
            spawn=[[x0+(x1-x0)*.35,(y0+y1)/2],[x0+(x1-x0)*.65,(y0+y1)/2]]
            warning=(warning or '')+'; campaign spawn coordinates require editor verification'
        # Verified infantry breeds shipped with the installed game.
        with open_archive(Path(cfg['mow'])/'resource/gamelogic.pak') as g:
            for a in roster:
                if a.get('breed') and 'set/breed/'+a['breed']+'.set' not in g.namelist(): raise BridgeError('Missing breed '+a['breed'])
                if a.get('infantry_equipment_tier',0)>=3 and a.get('breed','').endswith('/smg'):
                    # Change weapons without granting the elite breed's health
                    # and skill bonuses merely for owning newer equipment.
                    base=g.read('set/breed/mp/'+a['faction']+'/rifle.set').decode('utf8')
                    armed=g.read('set/breed/mp/'+a['faction']+'/sturmovik.set').decode('utf8')
                    inventory=block_at(armed,armed.index('{inventory'))
                    original=block_at(base,base.index('{inventory'))
                    name='hmb/'+a['faction']+'_infantry_3'
                    target=dest/('resource/set/breed/'+name+'.set');target.parent.mkdir(parents=True,exist_ok=True)
                    base=inline_breed_includes(base,'set/breed/mp/'+a['faction']+'/rifle.set',g)
                    target.write_text(base.replace(original,inventory),encoding='utf8')
                    a['breed']=name
    if cfg.get('linked_map_resources',False):
        if virtual!='single/hmb/battle':raise BridgeError('Linked map resources require the stable mission menu path')
        if not re.fullmatch(r'[0-9a-f]{32}',b['id']):raise BridgeError('Invalid map resource UUID')
        # All stock map paths are already registered by the running engine.
        # Newly added mod directories are not reliably visible until remount.
        resource_path=map_name
        resource_dir=output/'source-map-evidence';resource_dir.mkdir(parents=True,exist_ok=True)
        for native in list(mission_dir.iterdir()):
            if not native.resolve().is_relative_to(dest.resolve()) or not resource_dir.resolve().is_relative_to(output.resolve()):
                raise BridgeError('Map resource move escapes the generated mod')
            shutil.move(str(native),str(resource_dir/native.name))
        from .map_resources import bind_land
        with open_archive(Path(cfg['mow'])/'resource/entity/e1.pak') as entity_archive:
            land_definition=entity_archive.read('service/land/land').decode('utf8')
        link=bind_land(map_text,land_definition,resource_path)
        (mission_dir/'map').write_bytes(link.encode('utf8'))
        b['map_resource_path']=resource_path
        write_json(dest/'hmb-map-link.json',{'battle_id':b['id'],'mission_path':virtual,
            'resource_path':resource_path,'native_archive_source':True,'binding':'explicit_land',
            'map_link_sha256':digest(link.encode('utf8')),'experimental':True})
    pather=re.search(r'\{pather ([^}]+)\}',map_text)
    if not pather: raise BridgeError('Map has no verified pathing bounds')
    bounds=list(map(float,pather[1].split()))
    positions=formation_positions(roster,spawn,bounds,cfg.get('infantry_spawn_spacing',140) if formation_report else 35,cfg.get('vehicle_spawn_spacing',500))
    boundary={'entities':[],'release':[],'report':{'enabled':False}}
    if cfg.get('preparation_boundaries',False) and cfg.get('preparation_seconds',60)>0:
        from .preparation import deployment_plan,build_boundaries,arrange_deployment,write_boundary_resources
        try:plan=deployment_plan(roster,positions,points,bounds,cfg.get('capture_radius',300))
        except BridgeError as error:
            if str(error)!='Formation is too close to objectives for safe preparation boundaries':raise
            positions,plan=arrange_deployment(b,roster,spawn,points,bounds,cfg)
        write_boundary_resources(dest,cfg)
        boundary=build_boundaries(plan)
        boundary['report']['enabled']=True
    ammunition={'actions':[],'report':{'enabled':False}}
    if cfg.get('supply_ammunition',False):
        from .ammunition import build_ammunition
        ammunition=build_ammunition(b,cfg,roster,dest);ammunition['report']['enabled']=True
    from .objectives import build_objectives,end_actions,node,trigger,ending_condition
    from .tactical_ai import assign_groups,support_positions
    ai_groups=assign_groups(roster,len(points),cfg,defending=b.get('player_side','attacker')=='attacker')
    defending_deployment={'enabled':False}
    if boundary['report'].get('enabled'):
        from .preparation import position_defending_ai
        positions,defending_deployment=position_defending_ai(b,roster,positions,points,bounds,plan,ai_groups,cfg)
    write_json(output/'defending-deployment.json',defending_deployment)
    ai_positions=support_positions(ai_groups,points,spawn[1],bounds,cfg)
    objectives=build_objectives(b,cfg,points,ai_groups,ai_positions,boundary['release'],ammunition['actions'])
    # Native loading assigns runtime MIDs in entity order. Put decorative
    # flags after the complete combat roster so they cannot shift actor IDs.
    rows=['{mission']
    for a in roster:
        player=a['player']; x,y=positions[a['mid']]
        a['spawn_position']=[x,y]
        uid=0xf0000+a['mid']; a['uid']=hex(uid)
        entity_type='Entity' if a['kind']=='vehicle' else 'Human'
        name=a['entity'] if a['kind']=='vehicle' else a['breed']
        state='' if a['kind']=='vehicle' else ' {FsmState "stand"}'
        rows.append(f' {{{entity_type} "{name}" {hex(uid)} {{Position {x:.2f} {y:.2f}}} {{Player {player}}} {{MID {a["mid"]}}}{state} }}')
        side_tag=('hmb_equipment_' if a['kind']=='vehicle' else 'hmb_')+a['side']
        ai_tags=(' "hmb_enemy"' if player==1 else '')+(' "hmb_ai_combat" "'+a['ai_group']+'"' if a.get('ai_group') else '')
        if a.get('ammunition_tag'):ai_tags+=' "'+a['ammunition_tag']+'"'
        rows.append(f' {{Tags "hmb_{b["id"]}" "hmb_roster" "{side_tag}"{ai_tags} {hex(uid)}}}')
        preparing=' {return_fire off} {weapon_prepare off}'
        rows.append(f' {{Brain {hex(uid)} {{Properties {{control {"user" if player==0 else "AI"}}} {{move_mode hold}}{preparing} }} }}')
    for a in roster:
        if a.get('parent_mid'):
            rows.append(f' {{Link {hex(0xf0000+a["mid"])} {{{hex(0xf0000+a["parent_mid"])} "{a["seat"]}"}} }}')
    rows+=objectives['markers']+boundary['entities']+[' {Environment "multi/multi_01"}',
           ' {Players {user 0} {alias 0 "player"} {alias 1 "enemy"} {diplomacy 1 1 0 0 0 0 0 0 1 1 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 1} }',
           ' {Fog 0}', ' {Helpers '+node('vars',*[node(json.dumps(v),node('value','0')) for v in objectives['variables']]), *objectives['zones'],objectives['waypoints'],objectives['tasks'],' {triggers',*objectives['triggers']]
    for side,winner in [('defender','attacker'),('attacker','defender')]:
        test=ending_condition(node('"1.entities"',node('selector',node('tag','hmb_'+side),node('state','"not dead"')),node('count',node('op','"=="'),node('value','0'))))
        rows.append(trigger('hmb_end_'+side,test,end_actions(b,winner)))
    rows+=[' } }','}']
    mi='\n'.join(rows)
    list(blocks(mi))
    (mission_dir/'0.mi').write_text(mi,encoding='utf8')
    campaign_menu(b,cfg,dest,archive)
    if objectives['score_labels']:
        label_file=dest/('localization/mission/'+virtual+'.lng')
        labels=label_file.read_text(encoding='utf8')
        labels=labels[:-1]+' '.join('{'+json.dumps(key)+' '+json.dumps(value,ensure_ascii=False)+'}' for key,value in objectives['score_labels'].items())+'}'
        label_file.write_text(labels,encoding='utf8')
    (dest/'mod.info').write_text('{mod {name "HOI4_MoW_Bridge"} {desc "Experimental HOI4 tactical battle"} {minGameVersion "3.262"} {maxGameVersion "3.262"}}',encoding='utf8')
    if cfg.get('preinstalled_map_slots',False):
        # Every terrain file stays in its original relative namespace. No SDL
        # includes or Land overrides: geometry is immutable for this slot.
        immutable={p.relative_to(dest).as_posix():digest(p.read_bytes()) for p in mission_dir.rglob('*')
                   if p.is_file() and p.name not in ('0.mi','interface.set')}
        write_json(dest/'hmb-map-slot.json',{'schema':1,'source_map':map_name,'mission_path':virtual,'immutable':immutable})
    write_json(output/'battle.json',b); write_json(output/'roster.json',roster)
    write_json(output/'difficulty.json',difficulty)
    write_json(output/'preparation.json',boundary['report']);write_json(output/'ammunition.json',ammunition['report'])
    write_json(output/'ai-plan.json',{**objectives['ai'],'destinations':{g['tag']:[ai_positions[g['tag'],p] for p in range(len(points))] for g in ai_groups}})
    if formation_report: write_json(output/'formations.json',formation_report)
    write_json(output/'mission_manifest.json',{'battle_id':b['id'],'mission_path':virtual,'source_map':map_name,'terrain_note':warning,
               'weather':b.get('weather',{'known':False}),'difficulty':difficulty,
               'source_archive_sha256':digest(archive.read_bytes()) if archive.stat().st_size<100_000_000 else 'not hashed (large)',
               'scaling':{'soldiers_per_actor':cfg['soldiers_per_actor'],'max_infantry_per_side':cfg['max_infantry_per_side']},
               'organization_scaling':{'verified_snapshot':b.get('organization_snapshot',{}),
                   'applied':bool(b.get('organization_snapshot')),'rounding':'ceil per positive component, minimum one; complete crews',
                   'loss_weights':'original strategic manpower and equipment redistributed over deployed actors'},
               'objectives':objectives['rules'],'ai':objectives['ai'],'stage':'generated; engine load and autosave schema require verification','campaign_menu':'native metadata prepared; regular-game menu not yet verified','actor_count':len(roster)})
    return {'path':str(dest),'mission_path':virtual,'map':map_name,'actors':len(roster),'warning':warning}

def saved_variable(text,name):
    """AS2 3.262.1 mission.scn Helpers/vars/{name {value N}}."""
    outer=list(blocks(text)); content=outer[0][1:-1] if len(outer)==1 else text
    found=[]
    for helper in blocks(content):
        if not re.match(r'\{Helpers\b',helper): continue
        for section in blocks(helper[1:-1]):
            if not re.match(r'\{vars\b',section): continue
            for entry in blocks(section[1:-1]):
                if not re.match(r'\{"'+re.escape(name)+r'"\s',entry): continue
                value=re.findall(r'\{value\s+(-?\d+)\}',entry)
                if len(value)!=1: raise BridgeError('Invalid saved variable '+name)
                found.append(int(value[0]))
    if len(found)!=1: raise BridgeError('Cannot verify unique saved variable '+name)
    return found[0]

def vehicle_destroyed(entity):
    # AS2 counts both burned wrecks and unburned knocked-out hulls as lost.
    # A broken engine, track or repairable turret is insufficient evidence.
    parts=list(blocks(entity[1:-1]))
    able=' '.join(p for p in parts if p.startswith('{Able '))
    # Terminal saves also preserve fully exploded hulls/guns and the native
    # Burned marker on trucks whose body component is otherwise omitted.
    burned=any(re.match(r'\{Extender "burning"\s',p) and re.search(r'\{Burned\}',p) for p in parts)
    broken=any(re.match(r'\{Interaction\b',p) and re.search(r'\{Flags\s+[^}]*"broken"',p) for p in parts)
    if burned and broken and '"burning"' in able:return True
    body=next((p for p in parts if re.match(r'\{Component "body"\s',p)),None)
    if not body or not re.search(r'\{State (?:broken|destroyed)\}',body):return False
    if re.search(r'\{RepairTimeLeft\b',body):return False
    if '"-repaired"' in able:return True
    operatable=any(re.match(r'\{Operatable\b',p) for p in parts)
    chassis=any(re.match(r'\{Chassis\b',p) and re.search(r'\{Broken\}',p) for p in parts)
    return not operatable and chassis and broken and '"-select"' in able

def saved_statistics(text):
    outer=list(blocks(text)); content=outer[0][1:-1] if len(outer)==1 else text
    result={}
    for section in blocks(content):
        if not re.match(r'\{Statistics\b',section): continue
        for processor in blocks(section[1:-1]):
            player=re.search(r'\{player "(\d+)"\}',processor)
            if not player: continue
            counts={'man':0,'vehicle':0}
            for category in blocks(processor[1:-1]):
                kind=re.match(r'\{(man|vehicle)\b',category)
                if kind:
                    lost=re.search(r'\{lost (\d+)\}',category)
                    counts[kind[1]]=int(lost[1]) if lost else 0
            pid=int(player[1])
            if pid in result: raise BridgeError('Duplicate player statistics')
            result[pid]=counts
    return result

def analyze_saved_actors(roster,text,game_text=None,terminal_snapshot=False):
    entities={}; outer=list(blocks(text)); content=outer[0][1:-1] if len(outer)==1 else text
    for entity in blocks(content):
        if not re.match(r'\{(?:Human|Entity)\s',entity): continue
        mid=re.search(r'\{MID (\d+)\}',entity)
        if mid:
            key=int(mid[1])
            if key in entities: raise BridgeError('Duplicate actor MID in save: '+str(key))
            entities[key]=entity
    dead=[]; missing=[]; inferred=[]; culled=[]
    for a in roster:
        entity=entities.get(a['mid'])
        if entity is None: missing.append(a); continue
        expected=a.get('entity',a.get('breed'))
        if expected:
            actual=re.match(r'\{(?:Human|Entity) "([^\"]+)"',entity)
            if not actual or actual[1]!=expected: raise BridgeError('Saved actor identity does not match roster MID '+str(a['mid']))
        player=re.search(r'\{Player (\d+)\}',entity)
        if player and int(player[1])!=a['player']: raise BridgeError('Saved actor player does not match roster MID '+str(a['mid']))
        if a['kind']=='vehicle':
            if vehicle_destroyed(entity): dead.append(a['mid'])
        elif re.search(r'\{(?:Dead|dead)\b|\{FsmState "dead"\}',entity): dead.append(a['mid'])
    statistics=saved_statistics(game_text) if game_text else {}
    for a in missing:
        # AS2 removes crew killed inside a burned hull. Require both the
        # destroyed parent and exact engine casualty totals; no generic guess.
        if a['kind']=='crew' and a.get('parent_mid') in dead and statistics:
            dead.append(a['mid']); inferred.append(a['mid'])
        elif terminal_snapshot and statistics and a['kind']!='vehicle':
            # Observed terminal autosave removes old corpses. Accept removal
            # only at verified gameover and if every exact casualty count fits.
            dead.append(a['mid']); culled.append(a['mid'])
        else: raise BridgeError('Actor missing without verified destruction evidence: '+str(a['mid']))
    if statistics:
        for player in set(a['player'] for a in roster):
            counts={'man':sum(a['mid'] in dead and a['kind']!='vehicle' for a in roster if a['player']==player),
                    'vehicle':sum(a['mid'] in dead and a['kind']=='vehicle' for a in roster if a['player']==player)}
            if statistics.get(player)!=counts: raise BridgeError('Actor losses do not match native player statistics: player='+str(player)+' actors='+str(counts)+' native='+str(statistics.get(player)))
    return {'dead_mids':sorted(dead),'removed_crew_mids':sorted(inferred),'culled_human_mids':sorted(culled),'native_statistics':statistics}

def terminal_autosave_winner(b,game_text,progress_path):
    """AS2 autosave observed during the ending trigger's final delay.

    Helpers/vars remain initial in this engine snapshot. Cross-check runtime
    thread position against the completed gameover record for the same UUID.
    """
    outer=list(blocks(game_text)); content=outer[0][1:-1] if len(outer)==1 else game_text
    active=[]
    for section in blocks(content):
        if not re.match(r'\{Threads\b',section): continue
        for thread in blocks(section[1:-1]):
            match=re.match(r'\{trigger "hmb_(end|score_win|time_win)_(attacker|defender)"',thread)
            if match and re.search(r'\{current "/3/"\}',thread) and re.search(r'\{state "/3/"\s*\{delay 1\}',thread):
                active.append(('defender' if match[2]=='attacker' else 'attacker') if match[1]=='end' else match[2])
    if len(active)!=1: raise BridgeError('No unique terminal autosave thread')
    raw=Path(progress_path).read_bytes(); text=raw.decode('utf-8-sig'); entries=[]
    for match in re.finditer(r'\{"'+re.escape(mission_path(b))+r':0"',text):
        entry=next(blocks(text[match.start():]))
        if 'HMB '+b['id'] in entry: entries.append(entry)
    if len(entries)!=1: raise BridgeError('No matching gameover record for terminal autosave')
    player=b.get('player_side','attacker'); enemy='defender' if player=='attacker' else 'attacker'
    entry=entries[0]
    # completed is a persistent unlock marker: it survives later defeats.
    # Only the outro belonging to this exact battle records the new outcome.
    if 'mission/outro_failed' in entry or 'Поражение' in entry: recorded=enemy
    elif 'mission/outro_completed' in entry or 'mission/outro_win' in entry or 'Победа' in entry: recorded=player
    else: raise BridgeError('Terminal autosave gameover record is not recognized')
    if active[0]!=recorded: raise BridgeError('Autosave trigger and recorded outcome disagree')
    return recorded,raw

def parse_result(b,roster,path,progress_path=None):
    path=Path(path)
    if path.name=='game_progress.set': return parse_progress_result(b,roster,path)
    if path.is_dir():
        native=path/'mission.scn'
        files=[native] if native.is_file() else list(path.rglob('*.mi'))
        if len(files)!=1: raise BridgeError('Select the exact saved mission .mi file')
        path=files[0]
    game_raw=None
    if zipfile.is_zipfile(path):
        with open_archive(path) as z:
            names=[n for n in z.namelist() if n.endswith(('.mi','/mission.scn')) or n=='mission.scn']
            if len(names)!=1: raise BridgeError('Expected one saved .mi in archive')
            raw=z.read(names[0])
            companions=[n for n in z.namelist() if n=='game.scn' or n.endswith('/game.scn')]
            if len(companions)==1: game_raw=z.read(companions[0])
    else:
        raw=path.read_bytes()
        companion=path.parent/'game.scn'
        if path.name=='mission.scn' and companion.is_file(): game_raw=companion.read_bytes()
    text=raw.decode('utf-8-sig')
    if 'hmb_'+b['id'] not in text: raise BridgeError('Save is from a different tactical battle')
    game_text=game_raw.decode('utf-8-sig') if game_raw else None
    progress_raw=None; terminal=False
    if saved_variable(text,'hmb_finished')==1:
        value=saved_variable(text,'hmb_winner')
        if value not in (1,2): raise BridgeError('Ambiguous tactical winner')
        winner='attacker' if value==1 else 'defender'
        if game_text:
            progress_path=Path(progress_path or config()['mow_progress'])
            recorded,progress_raw=terminal_autosave_winner(b,game_text,progress_path);terminal=True
            if winner!=recorded: raise BridgeError('Saved winner and native completion disagree')
    elif game_text:
        progress_path=Path(progress_path or config()['mow_progress'])
        winner,progress_raw=terminal_autosave_winner(b,game_text,progress_path);terminal=True
    else: raise BridgeError('Tactical battle is not finished')
    audit=analyze_saved_actors(roster,text,game_text,terminal_snapshot=terminal)
    evidence={'kind':'mow_save','path':str(path.resolve()),'sha256':digest(raw),'adapter':'AS2 3.262.1 mission.scn','actor_audit':audit}
    if game_raw:
        evidence['statistics_sha256']=digest(game_raw)
        if not zipfile.is_zipfile(path): evidence['companions']=[{'path':str((path.parent/'game.scn').resolve()),'sha256':digest(game_raw)}]
    if progress_raw:
        evidence.setdefault('companions',[]).append({'path':str(progress_path.resolve()),'sha256':digest(progress_raw)})
        evidence['completion']='terminal trigger /3/ plus matching gameover record'
    return calculate_result(b,roster,winner,audit['dead_mids'],evidence)

def parse_progress_result(b,roster,path):
    """Read the real gameover record observed in AS2 3.262.1 editor.

    The engine writes aggregate kill/loss counters, not actor identities. Limit
    this verified adapter to one infantry division per side and two players.
    """
    for side in ('attacker','defender'):
        if len(b[side]['divisions'])!=1:
            raise BridgeError('Verified progress adapter supports one infantry division per side only')
    if any(a['kind']!='infantry' for a in roster): raise BridgeError('Progress adapter is infantry-only')
    raw=Path(path).read_bytes(); text=raw.decode('utf-8-sig')
    found=[]
    for match in re.finditer(r'\{"'+re.escape(mission_path(b))+r':0"',text):
        entry=next(blocks(text[match.start():]))
        if 'HMB '+b['id'] in entry: found.append(entry)
    if len(found)!=1: raise BridgeError('No unique finished record for this battle ID')
    entry=found[0]
    player_side=b.get('player_side','attacker'); enemy_side='defender' if player_side=='attacker' else 'attacker'
    if 'mission/outro_failed' in entry or 'Поражение' in entry: winner=enemy_side
    elif 'mission/outro_completed' in entry or 'mission/outro_win' in entry or 'Победа' in entry: winner=player_side
    else: raise BridgeError('Unrecognized gameover outcome; inspect real victory record')
    stat=re.search(r'\{stat "((?:\\.|[^"\\])*)"\}',entry)
    if not stat: raise BridgeError('Missing engine casualty statistics')
    # The Russian strings in the installed game include inline <x(135)> markup.
    lines=stat[1].replace('\\n','\n').splitlines()
    counts=[]
    for line in lines:
        numbers=re.search(r'(?:<x\(\d+\)>\s*)?(\d+)\s+(?:Живой силы|Manpower)[,\s]+(\d+)',line,re.I)
        if numbers: counts.append((int(numbers[1]),int(numbers[2])))
    if len(counts)!=2 or any(vehicles for _,vehicles in counts):
        raise BridgeError('Unsupported or incomplete engine statistics')
    casualties={player_side:counts[1][0],enemy_side:counts[0][0]}
    losses={}
    for side in ('attacker','defender'):
        n=sum(1 for a in roster if a['side']==side)
        lost=casualties[side]
        if not 0<=lost<=n: raise BridgeError('Casualty count exceeds exported force')
        ratio=lost/n; manpower=b[side]['divisions'][0]['manpower']
        losses[side]=[{'index':0,'manpower_lost':round(manpower*ratio),'loss_ratio':ratio}]
    from .policy import apply_loss_policy
    losses,policy=apply_loss_policy(b,losses,winner)
    return {'schema':1,'battle_id':b['id'],
        'battle_sha256':digest(json.dumps(b,sort_keys=True).encode()),'winner':winner,
        'casualties':casualties,'losses':losses,'loss_policy':policy,'evidence':{
            'kind':'mow_progress','path':str(Path(path).resolve()),'sha256':digest(raw),
            'adapter':'AS2 3.262.1 game_progress.set (defeat verified)',
            'limitation':'aggregate engine kill counters; no individual actor identities or equipment'}}
