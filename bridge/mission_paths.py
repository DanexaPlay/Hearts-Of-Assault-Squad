"""Bounded virtual paths for immutable per-battle GEM resources."""
import re,hashlib
from pathlib import Path
from .core import BridgeError

LEGACY='single/hmb/battle'

def map_slot(source_map):
    if not isinstance(source_map,str) or not re.fullmatch(r'(?:multi|single)/[a-z0-9_-]+(?:/[a-z0-9_-]+)*',source_map):
        raise BridgeError('Invalid native map identity')
    return 'single/hmb/map_'+hashlib.sha256(source_map.encode('utf8')).hexdigest()[:16]


def mission_path(b):
    value=b.get('mission_path',LEGACY)
    if value==LEGACY:return value
    if value.startswith('single/hmb/map_'):
        if value!=map_slot(b.get('map_source')):raise BridgeError('Mission slot does not match its native map')
        return value
    expected='single/hmb/battle_'+str(b.get('id',''))
    if value!=expected or not re.fullmatch(r'single/hmb/battle_[0-9a-f]{32}',value):
        raise BridgeError('Mission path does not belong to this battle UUID')
    return value


def assign_mission_path(b):
    if not re.fullmatch(r'[0-9a-f]{32}',str(b.get('id',''))):raise BridgeError('A battle UUID is required for unique mission resources')
    b['mission_path']='single/hmb/battle_'+b['id']
    return mission_path(b)


def installed_mission(target,installation):
    rel=installation.get('mission_relative_path','resource/map/'+LEGACY+'/0.mi')
    if not isinstance(rel,str) or not re.fullmatch(r'resource/map/single/hmb/(?:battle(?:_[0-9a-f]{32})?|map_[0-9a-f]{16})/0\.mi',rel):
        raise BridgeError('Invalid installed mission path')
    target=Path(target).resolve();path=target/rel
    if not path.resolve().is_relative_to(target):raise BridgeError('Installed mission escapes the mod folder')
    return path
