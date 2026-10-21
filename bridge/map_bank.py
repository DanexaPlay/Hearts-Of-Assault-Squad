"""Preinstalled full terrain namespaces; never replace live cached geometry."""
import copy,re,uuid,zipfile,shutil
from pathlib import Path
from .core import BridgeError,read_json,write_json,digest
from .mission_paths import map_slot

def configured_maps(cfg):
    return sorted({name for group in ('maps','winter_maps') for choices in cfg.get(group,{}).values() for name in choices},key=map_slot)

def supported_maps(cfg):
    """Campaign maps without capture anchors need separate authoring/proof."""
    with zipfile.ZipFile(Path(cfg['mow'])/'resource/map.pak') as archive:
        names=set(archive.namelist())
    selected=configured_maps(cfg)
    return [n for n in selected if 'map/'+n+'/battle_zones.mi' in names], [n for n in selected if 'map/'+n+'/battle_zones.mi' not in names]

def validate_slot_package(source,mission_rel):
    source=Path(source)
    slot=read_json(source/'hmb-map-slot.json')
    if slot.get('schema')!=1 or slot.get('mission_path')!=map_slot(slot.get('source_map')):
        raise BridgeError('Invalid map-slot identity')
    prefix='resource/map/'+slot['mission_path']+'/'
    if mission_rel.as_posix()!=prefix+'0.mi':raise BridgeError('Map-slot mission mismatch')
    immutable=slot.get('immutable',{})
    actual={p.relative_to(source).as_posix():digest(p.read_bytes()) for p in (source/prefix).rglob('*')
            if p.is_file() and p.name not in ('0.mi','interface.set')}
    if not immutable or immutable!=actual or any(prefix+name not in immutable for name in ('map','map.ply','map.net')):
        raise BridgeError('Incomplete or changed map-slot terrain')
    for rel in immutable:
        if not (source/rel).resolve().is_relative_to(source.resolve()):raise BridgeError('Unsafe map-slot resource')
    return slot

def validate_installed_bank(target):
    target=Path(target).resolve()
    marker=target/'hmb-map-bank.json'
    if not marker.is_file():raise BridgeError('Map bank is not installed; run Prepare_Map_Bank.cmd with MoW closed')
    bank=read_json(marker)
    if bank.get('schema')!=1 or not bank.get('slots'):raise BridgeError('Invalid map bank')
    paths=[]
    for slot in bank['slots']:
        virtual=map_slot(slot.get('source_map'))
        if slot.get('mission_path')!=virtual:raise BridgeError('Invalid map-bank identity')
        paths.append(virtual)
        immutable=slot.get('immutable',{})
        if not immutable:raise BridgeError('Missing bank terrain manifest')
        for rel,expected in immutable.items():
            path=target/rel
            if not rel.startswith('resource/map/'+virtual+'/') or not path.resolve().is_relative_to(target):
                raise BridgeError('Unsafe bank terrain path')
            if not path.is_file() or digest(path.read_bytes())!=expected:raise BridgeError('Installed bank terrain differs: '+rel)
        for rel in ('resource/map/'+virtual+'/0.mi','resource/map/'+virtual+'/interface.set','localization/mission/'+virtual+'.lng'):
            if not (target/rel).is_file():raise BridgeError('Incomplete map-bank registration')
    if len(set(paths))!=len(paths) or paths!=sorted(paths):raise BridgeError('Map-bank order is invalid')
    return bank

def prepare_bank(cfg,fixture,output,install=True):
    """Called only with a closed engine and the strategic worker lock held."""
    from .gem import generate
    from .transition import install_generated_mod
    output=Path(output);target=Path(cfg['mow_live_mod'])
    slots=[]
    for index,name in enumerate(configured_maps(cfg)):
        print('Preparing terrain '+str(index+1)+': '+name,flush=True)
        b=copy.deepcopy(fixture)
        b.update(id=uuid.uuid4().hex,terrain='plains',river_crossing=False,weather={'known':False},source='map_bank_fixture: no strategic import')
        settings={**cfg,'maps':{'plains':[name]},'preinstalled_map_slots':True,'unique_mission_paths':False,'linked_map_resources':False}
        stage=output/('slot_'+str(index));generate(b,settings,stage)
        slot=validate_slot_package(stage/'mow_mod',Path('resource/map/'+b['mission_path']+'/0.mi'))
        slots.append(slot)
    bank={'schema':1,'slots':slots,'production_enabled':False,'requires_live_terrain_verification':True}
    write_json(output/'bank.json',bank)
    if not install:return bank
    # All generation and validation completes before the first install.
    for index,slot in enumerate(slots):
        stage=output/('slot_'+str(index))
        install_generated_mod(stage/'mow_mod',target,stage,initialize_bank=True)
    # AS2 discovers old directories even when interface.set was removed.
    # Closed-engine setup archives whole obsolete directories outside the mod.
    campaign=target/'resource/map/single/hmb';displaced=output/'displaced-missions'
    for old in list(campaign.iterdir()):
        if not old.is_dir() or not re.fullmatch(r'battle(?:_[0-9a-f]{32})?|resources_[0-9a-f]{32}',old.name):continue
        destination=displaced/old.name
        if not old.resolve().is_relative_to(target.resolve()) or not destination.resolve().is_relative_to(output.resolve()):
            raise BridgeError('Unsafe obsolete mission archive path')
        displaced.mkdir(parents=True,exist_ok=True);shutil.move(str(old),str(destination))
    write_json(target/'hmb-map-bank.json',bank)
    validate_installed_bank(target)
    return bank
