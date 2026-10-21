"""Build tactical forces from every saved battalion and support company."""
import math,re,zipfile
from pathlib import Path
from .archives import open_archive
from .clausewitz import parse
from .core import BridgeError,resolve_country,vanilla_data_compatible
from .equipment import allocate_models,vehicle_equivalent,distribute_equipment,tier
from .readiness import organization_ratio,deployed_count

VEHICLES={
 'ger':{'light_tank':'pz1b','medium_tank':'pz4g','heavy_tank':'pz6e','artillery':'lefh18','anti_tank':'pak36','anti_air':'flak38','rocket':'nebelwerfer41','motorized':'blitz3_6','mechanized':'sdkfz251_1','recon':'sdkfz222','tank_destroyer':'hetzer','sp_artillery':'wespe'},
 'rus':{'light_tank':'t26','medium_tank':'t34_2','heavy_tank':'kv1','artillery':'zis3','anti_tank':'zis2','anti_air':'k61','rocket':'bm13','motorized':'zis5','mechanized':'m3','recon':'ba64','tank_destroyer':'su85','sp_artillery':'su76'},
 'usa':{'light_tank':'m5a1','medium_tank':'m4a3_75','heavy_tank':'m26_pershing','artillery':'m2a1l','anti_tank':'m1_57mm','anti_air':'bofors','rocket':'m4a4_tulip','motorized':'gmc','mechanized':'m3_usa','recon':'m8grayhound','tank_destroyer':'m10wolverine','sp_artillery':'m7'},
 'eng':{'light_tank':'mk7','medium_tank':'mk3','heavy_tank':'churchill_mk_vii','artillery':'pdr25','anti_tank':'qf2','anti_air':'bofors','rocket':'land_mattress','motorized':'bedford','mechanized':'universal_carrier','recon':'mk2daimler','tank_destroyer':'archer','sp_artillery':'bishop'},
 'jap':{'light_tank':'ha-go','medium_tank':'chi-ha57','heavy_tank':'chi-ri','artillery':'t90_75m','anti_tank':'type94','anti_air':'type2_20mm','rocket':'type4_200mm','motorized':'isuzutx40','mechanized':'ho-ha3mgun','recon':'type93scout','tank_destroyer':'ho-ni1','sp_artillery':'ho-ro'}
}
for faction,entity in {'ger':'ostwind','rus':'zsu37','usa':'m16','eng':'crusaderaa1','jap':'type2_20mm'}.items():
    VEHICLES[faction]['sp_anti_air']=entity

def unit_definitions(game_dir):
    definitions={}
    for path in sorted((Path(game_dir)/'common/units').glob('*.txt')):
        tree=parse(path.read_text(encoding='utf-8-sig'))
        for group in tree.all('sub_units'):
            for node in group.children:
                if not node.key or node.value is not None: continue
                need={}
                for entries in node.all('need'):
                    for item in entries.children:
                        if item.key and item.value is not None: need[item.key]=float(item.value)
                definitions[node.key]={'manpower':float(node.get('manpower',0)),'need':need,'max_strength':float(node.get('max_strength',0))}
    return definitions

def equipment_family(model):
    if model.startswith('motorized_equipment'): return 'motorized_equipment'
    if model.startswith('mechanized_equipment'): return 'mechanized_equipment'
    return re.sub(r'_\d+$','',model)

def component_role(component):
    name=component['type']
    if 'sp_anti_air' in name: return 'sp_anti_air'
    if 'sp_artillery' in name: return 'sp_artillery'
    if 'tank_destroyer' in name: return 'tank_destroyer'
    if 'armor' in name or 'tank' in name:
        return 'heavy_tank' if any(x in name for x in ('heavy','modern')) else ('light_tank' if 'light' in name else 'medium_tank')
    if 'rocket' in name: return 'rocket'
    if 'artillery' in name: return 'artillery'
    if 'anti_tank' in name: return 'anti_tank'
    if 'anti_air' in name: return 'anti_air'
    if 'mechanized' in name: return 'mechanized'
    if 'motorized' in name: return 'motorized'
    if name in ('armored_car','armored_car_recon','armored_recon','mot_recon','light_tank_recon'): return 'recon'
    return 'infantry'

def catalog(cfg):
    root=Path(cfg['mow'])/'resource'
    entities={}
    for path in sorted((root/'entity').glob('*.pak')):
        with open_archive(path) as z:
            for name in z.namelist():
                if name.startswith('-vehicle/') and name.endswith('.def'):
                    entities[Path(name).stem]=(str(path),name)
    with open_archive(root/'gamelogic.pak') as z: breeds={n[10:-4] for n in z.namelist() if n.startswith('set/breed/') and n.endswith('.set')}
    return entities,breeds

def crew_places(entity,entities):
    archive,name=entities[entity]
    with open_archive(archive) as z:
        text=z.read(name).decode('utf8',errors='replace')
        # Some vehicles declare their operative seats in a local extension.
        for ext in re.findall(r'\{extension "([^"/]+\.ext)"',text,re.I):
            relative=str(Path(name).parent/ext).replace('\\','/')
            if relative in z.namelist(): text+='\n'+z.read(relative).decode('utf8',errors='replace')
    text=re.sub(r';[^\r\n]*','',text)
    cannon='/cannon/' in name
    car='/car/' in name
    seats=[]
    for match in re.finditer(r'\("crew_(\d+)_human(?:_extended)?"',text):
        count=int(match[1])
        choices=['gunner','commander'] if cannon else ['driver','commander'] if car else ['gunner','driver','charger','commander']
        seats.extend(choices[:count])
    if '("crew_wheeled_gun")' in text:
        seats.extend(['gunner','commander','driver1','driver2','seat1','seat2'])
    elif '("crew_gun")' in text: seats.extend(['gunner','commander','driver1','driver2'])
    seats += re.findall(r'\("crew_human(?:_visible(?:_anm)?|_gunner)?"\s+place\((\w+)\)',text)
    seats += re.findall(r'\{place "(driver|gunner|charger|commander|gunner2)"\s+\{(?:group|visor|LinkBone)',text,re.I)
    if not seats:
        seats=['driver'] if '/car/' in name or '/btr/' in name else ['gunner']
    # Passenger seats are represented by the component's dismounted infantry,
    # not extra tank crew. Gun seats belong to the native full artillery detail.
    if not cannon: seats=[seat for seat in seats if not seat.startswith(('seat','passenger'))]
    return list(dict.fromkeys(seats))

def build_roster(b,cfg):
    if not vanilla_data_compatible(b.get('source_mods',[])):
        raise BridgeError('Full composition currently uses vanilla unit definitions; disable mods or provide their definitions')
    definitions=unit_definitions(cfg['hoi4']); entities,breeds=catalog(cfg)
    roster=[]; report=[]
    for side,player in [('attacker',0),('defender',1)]:
        player=0 if side==b.get('player_side','attacker') else 1
        faction=resolve_country(b[side]['country'],b[side]['ideology'],cfg)
        for di,division in enumerate(b[side]['divisions']):
            readiness=organization_ratio(b,division)
            template=division.get('template')
            if not template or not template.get('components'): raise BridgeError('Full division template is required')
            components=[]
            for ci,component in enumerate(template['components']):
                if component['type'] not in definitions: raise BridgeError('Unknown battalion '+component['type']+'; mod unit definitions need a mapping')
                stats=definitions[component['type']]
                components.append({**component,'index':ci,'role':component_role(component),'stats':stats,'equipment':{}})
            total_weight=sum(c['stats']['manpower'] for c in components)
            if total_weight<=0: raise BridgeError('Template has no manpower definition')
            gear={}
            for equipment in division['equipment']:
                family=equipment_family(equipment['variant']['model'])
                gear.setdefault(family,[]).append(equipment)
            demands={family:sum(c['stats']['need'].get(family,0) for c in components) for family in gear}
            for c in components:
                for family,items in gear.items():
                    need=c['stats']['need'].get(family,0)
                    if need and demands[family]:
                        c['equipment'][family]=[{**e,'represented_amount':max(0,e['amount'])*need/demands[family]} for e in items]
                manpower=division['manpower']*c['stats']['manpower']/total_weight
                if manpower<=0: continue
                own=[]; role=c['role']; vehicle=None
                if role!='infantry':
                    vehicle=VEHICLES[faction][role]
                    if vehicle not in entities: raise BridgeError('Missing native vehicle '+vehicle)
                    candidates=[family for family in c['equipment'] if family not in ('infantry_equipment','support_equipment')]
                    priority='motorized_equipment' if role=='motorized' else 'mechanized_equipment' if role=='mechanized' else None
                    if priority and priority in candidates: candidates=[priority]
                    elif role in ('light_tank','medium_tank','heavy_tank','tank_destroyer','sp_artillery','sp_anti_air'): candidates=[f for f in candidates if 'tank' in f]
                    elif role in ('artillery','anti_tank','anti_air','rocket'): candidates=[f for f in candidates if 'motorized' not in f and 'mechanized' not in f]
                    available=sum(e['represented_amount'] for family in candidates for e in c['equipment'][family])
                    count=min(cfg.get('max_vehicles_per_component',3),max(1,math.ceil(available/cfg.get('equipment_per_vehicle',30)))) if available else 0
                    count=deployed_count(count,readiness)
                    models=allocate_models([e for family in candidates for e in c['equipment'][family]],count,preserve_variants=False)
                    for equipment in models:
                        chosen,note=vehicle_equivalent(faction,role,equipment['variant'],vehicle)
                        if chosen not in entities: raise BridgeError('Missing native equipment equivalent '+chosen)
                        own.append({'kind':'vehicle','entity':chosen,'role':role,'primary_families':candidates,'equipment_variant_id':equipment['variant_id'],'equipment_model':equipment['variant']['model'],'equipment_note':note})
                        vehicle_index=len(own)-1
                        for seat in crew_places(chosen,entities):
                            own.append({'kind':'crew','breed':f'mp/{faction}/tankman','seat':seat,'parent_local_index':vehicle_index})
                    if not count: c['note']='No available vehicle equipment; component represented by dismounted personnel'
                    if role=='sp_anti_air' and faction=='jap': c['note']='Native Japanese self-propelled AA unavailable; represented by native towed AA'
                if role=='infantry' and c['type'] not in ('infantry','engineer','field_hospital','signal_company'):
                    c['note']='Represented by native infantry/support personnel; specialist strategic bonuses are not simulated'
                if role in ('infantry','motorized','mechanized','recon') or not own:
                    count=deployed_count(max(1,math.ceil(manpower/cfg['soldiers_per_actor'])),readiness)
                    models=allocate_models(c['equipment'].get('infantry_equipment',[]),count,preserve_variants=False)
                    for j in range(max(count,len(models))):
                        equipment=models[j] if models else None
                        breed='saper' if c['type']=='engineer' else 'medic' if 'hospital' in c['type'] else 'radioman' if c['type']=='signal_company' else ('mgun' if j%8==7 else 'rifle')
                        level=tier(equipment['variant']) if equipment else 0
                        if breed=='rifle' and level>=2: breed='smg'
                        if f'mp/{faction}/{breed}' not in breeds: breed='rifle'
                        actor={'kind':'infantry','breed':f'mp/{faction}/{breed}'}
                        if equipment: actor.update(equipment_variant_id=equipment['variant_id'],equipment_model=equipment['variant']['model'],infantry_equipment_tier=level)
                        own.append(actor)
                humans=[a for a in own if a['kind']!='vehicle']
                for a in own: a['represented_manpower']=manpower/len(humans) if a['kind']!='vehicle' else 0
                first_mid=len(roster)+1
                for local_index,a in enumerate(own):
                    a.update(mid=first_mid+local_index,side=side,player=player,faction=faction,division_index=di,component_index=c['index'],battalion=c['type'],support=c['group']=='support')
                    needed=sum(c['stats']['need'].values())
                    available=sum(min(need,sum(e['represented_amount'] for e in c['equipment'].get(family,[]))) for family,need in c['stats']['need'].items())
                    a['equipment_readiness_ratio']=min(1,max(0,available/needed)) if needed else None
                    if 'parent_local_index' in a: a['parent_mid']=first_mid+a.pop('parent_local_index')
                    a['represented_equipment']=[]
                for family,equipments in c['equipment'].items():
                    distribute_equipment(own,humans,family,equipments)
                if any(a.get('breed') and a['breed'] not in breeds for a in own): raise BridgeError('Missing native crew breed for '+faction)
                roster.extend(own)
                report.append({'side':side,'division_index':di,'template':template['name'],'component':{k:v for k,v in c.items() if k!='stats'},'actors':len(own),'represented_manpower':manpower,'organization_ratio':readiness})
        if sum(a['side']==side for a in roster)>cfg.get('max_entities_per_side',240):
            raise BridgeError('Full battalion composition exceeds actor limit; raise soldiers_per_actor instead of dropping battalions')
    return roster,report
