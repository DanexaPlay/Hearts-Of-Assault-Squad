"""Observed HOI4 weather/provinces and weather/regions text-save adapter."""
import math,re
from pathlib import Path
from .clausewitz import parse
from .gem import block_at
from .core import BridgeError

CONDITIONS=('rain_light','rain_heavy','snow','blizzard','sandstorm','arctic_water')


def section(text,name):
    match=re.search(r'(?m)^\s*'+re.escape(name)+r'\s*=\s*\{',text)
    return block_at(text,text.index('{',match.start())) if match else None


def read_weather(text,provinces):
    match=re.search(r'(?m)^weather\s*=\s*\{',text)
    root=block_at(text,text.index('{',match.start())) if match else None
    if root is None:return {'provinces':{},'regions':{}}
    table=section(root,'provinces');result={'provinces':{},'regions':{}}
    if table:
        for province in set(provinces):
            match=re.search(r'(?m)^\s*"?'+str(int(province))+r'"?\s*=\s*\{',table)
            if not match:continue
            node=parse('entry='+block_at(table,table.index('{',match.start()))).one('entry')
            if int(node.get('province',-1))!=province:raise BridgeError('Weather province ID mismatch')
            # Observed province records use mud=yes/no as a presence flag,
            # as well as numeric mud values. Do not invent a thickness of 1.
            mud_raw=node.get('mud',0);mud_flag=mud_raw in ('yes','no')
            try:
                values={key:float(node.get(key,0)) for key in ('temperature','snow','water')}
                values['mud']=None if mud_flag else float(mud_raw)
            except (TypeError,ValueError) as error:
                raise BridgeError('Invalid saved weather values for province '+str(province)) from error
            if any(v is not None and not math.isfinite(v) for v in values.values()) or values['snow']<0:
                raise BridgeError('Invalid saved weather values')
            result['provinces'][str(province)]={'known':True,'temperature':values['temperature'],
                'snow_cover':values['snow'],'mud':values['mud'],'water':values['water'],
                'source':'HOI4 text save weather/provinces'}
            if mud_flag:result['provinces'][str(province)].update(mud_present=mud_raw=='yes',mud_value_kind='flag',mud_raw=mud_raw)
    regions=section(root,'regions')
    if regions:
        for node in parse('regions='+regions).one('regions').children:
            if not node.key:continue
            result['regions'][str(int(node.key))]={'conditions':[k for k in CONDITIONS if node.get(k)=='yes'],
                'source':'HOI4 text save weather/regions'}
    return result


def resolve_weather(campaign,province,game_dir):
    weather=campaign.get('weather',{})
    data=dict(weather.get('provinces',{}).get(str(province),{'known':False}))
    matches=[]
    for path in (Path(game_dir)/'map/strategicregions').glob('*.txt'):
        text=path.read_text(encoding='utf-8-sig')
        group=re.search(r'\bprovinces\s*=\s*\{([^}]+)\}',text)
        if group and str(province) in group[1].split():
            match=re.search(r'\bid\s*=\s*(\d+)',text)
            if match:matches.append(match[1])
    if len(matches)>1:raise BridgeError('Ambiguous weather region for province')
    if matches:
        region=matches[0];entry=weather.get('regions',{}).get(region,{})
        data.update(strategic_region=int(region),conditions=entry.get('conditions',[]))
        if entry:data.update(known=True,conditions_source=entry['source'])
    return data
