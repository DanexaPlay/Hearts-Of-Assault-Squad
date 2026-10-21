"""Curated native equipment equivalents; saved stocks determine the mix."""
import math,re
from .core import BridgeError

TANK_TIERS={
 'ger':{'light_tank':['pz1b','pz2f','pz2l'],'medium_tank':['pz3f','pz4g','pz5g'],'heavy_tank':['pz6e','pz6e','pz6bh']},
 'rus':{'light_tank':['t26','t60','t70'],'medium_tank':['t34_0','t34_2','t34_3'],'heavy_tank':['kv1','kv85','is2']},
 'usa':{'light_tank':['m5a1','m5a1','m24'],'medium_tank':['m4a3_75','m4a3_75','m4a3e8'],'heavy_tank':['m26_pershing']*3},
 'eng':{'light_tank':['mk7']*3,'medium_tank':['mk3','cromwell_mk_vii','m4a4_firefly'],'heavy_tank':['churchill_mk_vii']*3},
 'jap':{'light_tank':['ha-go']*3,'medium_tank':['chi-ha57','chi-he','chi-to'],'heavy_tank':['chi-ri']*3},
}

def tier(variant):
    model=variant.get('model','')
    match=re.search(r'_(\d+)$',model)
    return max(0,int(match[1])) if match else 1

def vehicle_equivalent(faction,role,variant,default):
    levels=TANK_TIERS.get(faction,{}).get(role)
    if not levels: return default,'Role equivalent; this equipment family has no curated generation mapping'
    level=max(1,tier(variant)); chosen=levels[min(level,3)-1]
    # The basic chassis has no direct native counterpart. Repeated entries are
    # explicit approximations, never fictitious assets or automatic upgrades.
    note='Saved chassis generation '+str(tier(variant))+'; curated native equivalent'
    if level>3 or len(set(levels))<3: note+=' (native catalog approximation)'
    return chosen,note

def allocate_models(items,count,preserve_variants=True):
    """At least one actor per positive saved variant, then proportional extras.

    With preserve_variants=True, actor count may exceed the component target
    to show minority models. False respects an organisation-reduced budget;
    unshown variants still retain their strategic equipment weight elsewhere.
    """
    items=[e for e in items if e['represented_amount']>0]
    if not items: return []
    if preserve_variants:count=max(count,len(items))
    elif count<=0:return []
    weights=[e['represented_amount'] for e in items]
    total=sum(weights); exact=[count*w/total for w in weights]
    minimum=1 if preserve_variants else 0
    assigned=[max(minimum,math.floor(v)) for v in exact]
    while sum(assigned)>count:
        i=max((i for i in range(len(items)) if assigned[i]>minimum),key=lambda i:(assigned[i]-exact[i],-i))
        assigned[i]-=1
    while sum(assigned)<count:
        i=max(range(len(items)),key=lambda i:(exact[i]-assigned[i],-i));assigned[i]+=1
    return [e for e,n in zip(items,assigned) for _ in range(n)]

def distribute_equipment(own,humans,family,equipments):
    """Variant-specific vehicles/infantry receive their own equipment stock."""
    for e in equipments:
        selected=[a for a in own if a.get('equipment_variant_id')==e['variant_id'] and
                  (a['kind']=='vehicle' and family in a.get('primary_families',[]) or a['kind']=='infantry' and family=='infantry_equipment')]
        recipients=selected or [a for a in own if a['kind']=='vehicle' and family in a.get('primary_families',[])] or humans
        if not recipients: raise BridgeError('No equipment recipient for '+family)
        for a in recipients: a['represented_equipment'].append({'variant_id':e['variant_id'],'family':family,'amount':e['represented_amount']/len(recipients)})
