"""Bind land mesh/height/grass to immutable stock paths, not launcher aliases."""
import re
from .core import BridgeError


def bind_land(text,native_definition,namespace):
    from .gem import block_at,blocks
    if not re.fullmatch(r'(?:multi|single)/[a-z0-9_-]+(?:/[a-z0-9_-]+)*',namespace):
        raise BridgeError('Invalid native map namespace')
    match=re.search(r'\{Land\s',text)
    if not match:raise BridgeError('Native map has no land descriptor')
    land=block_at(text,match.start())
    definition=next(blocks(native_definition))
    if not definition.startswith('{land'):raise BridgeError('Invalid native land definition')
    body=definition[len('{land'):-1]
    for name in ('map.ply','map.net','map.grs'):
        if body.count('"'+name+'"')!=1:raise BridgeError('Unexpected native land resource definition')
        body=body.replace('"'+name+'"','"/map/'+namespace+'/'+name+'"')
    result=text[:match.start()]+land[:-1]+body+'}'+text[match.start()+len(land):]
    list(blocks(result))
    return result


def validate_land_binding(text,namespace):
    from .gem import block_at
    match=re.search(r'\{Land\s',text)
    if not match:raise BridgeError('Missing linked land descriptor')
    land=block_at(text,match.start())
    for key,name in (('VolumeView','map.ply'),('Heightmap','map.net'),('Grass','map.grs')):
        if len(re.findall(r'\{'+key+r'\s+"'+re.escape('/map/'+namespace+'/'+name)+r'"',land))!=1:
            raise BridgeError('Land resource does not use the selected native map')
