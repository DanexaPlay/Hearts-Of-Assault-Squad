"""Tactical casualties represent a failed engagement, not strategic annihilation."""
import math
from .core import fraction,config

DEFAULT={'max_manpower_loss_ratio':0.25,'defeat_min_loss_ratio':0.02,'defeat_org_damage_ratio':0.90,'winner_org_damage_ratio':0.20}

def apply_loss_policy(b,losses,winner):
    policy={**DEFAULT,**b.get('loss_policy',config().get('loss_policy',{}))}
    for key,value in policy.items(): fraction(value,key)
    capped={}
    for side,values in losses.items():
        capped[side]=[]
        for loss in values:
            raw=fraction(loss['loss_ratio'],'tactical loss ratio')
            ratio=raw*policy['max_manpower_loss_ratio']
            if side!=winner: ratio=max(ratio,policy['defeat_min_loss_ratio'])
            ratio=min(ratio,policy['max_manpower_loss_ratio'])
            org=policy['defeat_org_damage_ratio'] if side!=winner else policy['winner_org_damage_ratio']
            manpower=b[side]['divisions'][loss['index']]['manpower']
            lost=math.floor(manpower*ratio+1e-9)
            capped[side].append({**loss,'tactical_loss_ratio':raw,'tactical_manpower_lost':loss['manpower_lost'],
                'loss_ratio':lost/manpower,'manpower_lost':lost,'organization_loss_ratio':org,'retreat_required':side!=winner})
    return capped,policy
