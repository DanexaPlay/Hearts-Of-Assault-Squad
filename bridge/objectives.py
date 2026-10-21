"""Native GEM control points, score, battle clock and mobile AI orders."""
import json
from .core import integer,BridgeError

def node(name,*children): return '{'+name+(' '+' '.join(children) if children else '')+'}'
def quote(value): return json.dumps(str(value),ensure_ascii=False)
def scalar(key,value): return node(key,quote(value) if isinstance(value,str) else str(value))
def condition(kind,*fields): return node('condition',scalar('type',kind),*fields)
def variable(name,op,value): return node('"set_i"',scalar('var',name+'$'),scalar('op',op),scalar('value',value))
def compare(name,op,value): return condition('cmp_i',scalar('var',name+'$'),scalar('op',op),scalar('value',value))
def if_action(test,*actions): return node('"if"',test,*actions)
def entities(side,point,op,value):
    return condition('entities',node('selector',scalar('tag','hmb_'+side),scalar('zone',point),scalar('state','not dead')),node('count',scalar('op',op),scalar('value',value)))
def trigger(name,test,actions): return node(quote(name),test,node('actions',*actions))
def start_trigger(name): return node('"trigger"',scalar('name',name))
def ending_condition(term):
    return node('condition',node('terms',term,node('"2.cmp_i"',scalar('var','hmb_finished$'),scalar('op','=='),scalar('value',0)),node('"3.cmp_i"',scalar('var','hmb_battle_started$'),scalar('op','=='),scalar('value',1))))

def started_condition():
    return node('condition',node('terms',node('"1.cmp_i"',scalar('var','hmb_battle_started$'),scalar('op','=='),scalar('value',1))))

def end_actions(b,winner):
    value=1 if winner=='attacker' else 2
    outcome='win' if winner==b.get('player_side','attacker') else 'loose'
    return [variable('hmb_winner','=',value),variable('hmb_finished','=',1),node('"autosave"'),node('"delay"',scalar('time',1)),node('"gameover"',scalar('result',outcome),scalar('message','HMB '+b['id']))]

def build_objectives(b,cfg,points,ai_groups=None,ai_positions=None,preparation_release=(),initial_actions=()):
    seconds=integer(cfg.get('battle_timer_seconds',900),'battle timer')
    target=integer(cfg.get('capture_score_to_win',100),'capture score')
    tick=integer(cfg.get('capture_tick_seconds',5),'capture tick')
    radius=integer(cfg.get('capture_radius',300),'capture radius')
    preparation=integer(cfg.get('preparation_seconds',60),'preparation duration',low=0)
    if not points: raise BridgeError('At least one capture point is required')
    if min(seconds,target,tick,radius)<=0: raise BridgeError('Battle rules must be positive')
    variables=['hmb_winner','hmb_finished','hmb_attacker_score','hmb_defender_score','hmb_score_lead','hmb_timeout_winner','hmb_battle_started','hmb_preparation_released']
    from .scoreboard import build_scoreboard
    scoreboard=build_scoreboard(b,target);variables+=scoreboard['variables']
    from .tactical_ai import build_director
    ai=build_director(b,cfg,points,ai_groups,ai_positions);variables+=ai['variables']
    zones=[]; waypoints=[]; markers=[]; triggers=[]
    for i,(x,y) in enumerate(points,1):
        point='hmb_point_'+str(i); owner=point+'_owner';variables.append(owner)
        zones.append(node('zone "circle"',node('position',str(x),str(y),'0'),scalar('Name',point),scalar('Radius',radius)))
        waypoints.append(node(quote(point),node('position',str(x),str(y),'0')))
        markers.append(node('Entity "flag_point_'+str((i-1)%3+1)+'" '+hex(0xfe000+i),node('Position',str(x),str(y)),node('Extender "map_point"',scalar('name','f'+str(i)),scalar('zoneA',12),scalar('zoneB',12),scalar('order',i),scalar('show','All'),scalar('visor','MapPoint'))))
        capture=[]
        for side,value in [('attacker',1),('defender',2)]:
            other='defender' if side=='attacker' else 'attacker'
            capture.append(if_action(entities(side,point,'>',0),if_action(entities(other,point,'==',0),variable(owner,'=',value))))
            capture.append(if_action(compare(owner,'==',value),if_action(entities(other,point,'==',0),variable('hmb_'+side+'_score','+',1),variable('hmb_score_lead','+' if side=='attacker' else '-',1))))
        # Recheck after the delay: another point can finish the battle while
        # this scoring coroutine sleeps. Do not accrue post-victory points.
        actions=[node('"delay"',scalar('time',tick)),if_action(compare('hmb_finished','==',0),*capture,start_trigger(point+'_tick'))]
        triggers.append(trigger(point+'_tick',started_condition(),[if_action(compare('hmb_finished','==',0),*actions)]))
    for winner in ('attacker','defender'):
        name='hmb_score_win_'+winner
        test=ending_condition(node('"1.cmp_i"',scalar('var','hmb_'+winner+'_score$'),scalar('op','>='),scalar('value',target)))
        triggers.append(trigger(name,test,end_actions(b,winner)))
        triggers.append(trigger('hmb_time_win_'+winner,ending_condition(node('"1.cmp_i"',scalar('var','hmb_timeout_winner$'),scalar('op','=='),scalar('value',1 if winner=='attacker' else 2))),end_actions(b,winner)))
    choose=node('"switch"',node('"case"',compare('hmb_score_lead','>',0),variable('hmb_timeout_winner','=',1)),node('"default"',variable('hmb_timeout_winner','=',2)))
    clock=[node('"timer"',scalar('time',seconds),scalar('title','$/hmb_clock')),node('"task"',scalar('name','hmb_points_goal'))]+scoreboard['initial_actions']+[node('"delay"',scalar('time',seconds)),if_action(compare('hmb_finished','==',0),choose)]
    prepare=[node('"timer"',scalar('time',preparation),scalar('title','$/hmb_preparation')),node('"delay"',scalar('time',preparation)),*preparation_release,variable('hmb_preparation_released','=',1),node('"actor_state"',node('selector',scalar('tag','hmb_roster'),scalar('state','not dead')),scalar('return_fire','on'),scalar('weapon_prepare','on')),*ai['initial'],variable('hmb_battle_started','=',1)]
    if cfg.get('preparation_probe_autosave',False):prepare.append(node('"autosave"'))
    triggers.append(trigger('hmb_prepare',node('condition'),prepare))
    variables.append('hmb_initial_snapshot')
    triggers.append(trigger('hmb_initial_snapshot',node('condition'),[*initial_actions,variable('hmb_initial_snapshot','=',1),node('"autosave"')]))
    triggers.append(trigger('hmb_clock',started_condition(),clock))
    triggers.append(ai['trigger']);zones+=ai['zones'];waypoints+=ai['waypoints']
    triggers.append(scoreboard['trigger'])
    return {'variables':variables,'zones':zones,'waypoints':node('waypoints "player"',*waypoints),'markers':markers,'triggers':triggers,
        'tasks':node('tasks',node('"hmb_points_goal"',scalar('desc','$/hmb_points_goal'),node('primary'),scalar('state','hidden')),*scoreboard['tasks']),
        'score_labels':scoreboard['labels'],'ai':ai['report'],
        'rules':{'preparation_seconds':preparation,'time_limit_seconds':seconds,'score_to_win':target,'tick_seconds':tick,'points':points,'radius':radius,'timeout':'higher score; ties retain defending province','stage':'generated; preparation, scoring and timer expiration require engine verification'}}
