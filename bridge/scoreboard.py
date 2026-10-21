"""Live score using shipped GEM task show/hide commands and localized labels."""
from .objectives import node,scalar,compare,variable,if_action,trigger,started_condition,start_trigger
from .core import BridgeError

def build_scoreboard(b,target):
    if target>1000: raise BridgeError('Native score display supports victory targets up to 1000')
    tasks=[];labels={};variables=['hmb_hud_changed'];initial=[];updates=[]
    player=b.get('player_side','attacker')
    for side in ('attacker','defender'):
        cached='hmb_hud_'+side;variables.append(cached)
        score='hmb_'+side+'_score'
        heading=('Ваши очки' if side==player else 'Очки противника')+' ('+b.get(side,{}).get('country',side)+')'
        for value in range(target+1):
            name='hmb_score_'+side+'_'+str(value)
            tasks.append(node('"'+name+'"',scalar('desc','$/'+name),node('primary'),scalar('state','hidden')))
            labels[name]=heading+': '+str(value)+' / '+str(target)
        initial.append(node('"task"',scalar('name','hmb_score_'+side+'_0')))
        checks=[];hide=[];show=[]
        for value in range(target+1):
            name='hmb_score_'+side+'_'+str(value)
            op='==' if value<target else '>='
            checks.append(node('"case"',compare(score,op,value),if_action(compare(cached,'!=',value),variable('hmb_hud_changed','=',1))))
            hide.append(node('"case"',compare(cached,'==',value),node('"task"',scalar('name',name),scalar('state','hide'))))
            show.append(node('"case"',compare(score,op,value),node('"task"',scalar('name',name)),variable(cached,'=',value)))
        updates.extend([variable('hmb_hud_changed','=',0),node('"switch"',*checks),if_action(compare('hmb_hud_changed','==',1),node('"switch"',*hide),node('"switch"',*show))])
    actions=[if_action(compare('hmb_finished','==',0),*updates,node('"delay"',scalar('time',1)),start_trigger('hmb_score_display'))]
    return {'tasks':tasks,'labels':labels,'variables':variables,'initial_actions':initial,
        'trigger':trigger('hmb_score_display',started_condition(),actions)}
