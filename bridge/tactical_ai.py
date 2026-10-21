"""Small native mission groups, support positions and event-based orders."""
import math
from .core import integer,BridgeError

GUNS={'artillery','anti_tank','anti_air','rocket','sp_artillery','sp_anti_air','tank_destroyer'}
ARMOR={'light_tank','medium_tank','heavy_tank','mechanized','recon'}
REAR_SUPPORT={'artillery','rocket','sp_artillery'}


def tactical_role(actor):
    # A HOI4 artillery battalion can be represented by AS2's direct-fire
    # ZIS-3. It must maneuver as an AT gun; strategic loss weights stay intact.
    return 'anti_tank' if actor.get('entity')=='zis3' else actor.get('role')


def assign_groups(roster,point_count,cfg,defending=False):
    integer(point_count,'AI point count')
    size=integer(cfg.get('ai_squad_size',6),'AI squad size')
    if size>12:raise BridgeError('AI infantry squads must not exceed 12 actors')
    groups=[];divisions={}
    for actor in roster:
        if actor['player']==1 and actor['kind']=='infantry':
            divisions.setdefault(actor.get('division_index',0),[]).append(actor)
    if defending:size=min(size,max(1,math.ceil(sum(map(len,divisions.values()))/point_count)))
    squads=[actors[i:i+size] for actors in divisions.values() for i in range(0,len(actors),size)]
    sector=0;garrisons=set()
    for index,actors in enumerate(squads):
        reserve=len(squads)>=4 and index%4==3
        home=(point_count//2+index//4)%point_count if reserve else sector%point_count
        if not reserve:sector+=1
        garrison=not reserve and (defending or len(squads)>=point_count) and home not in garrisons
        if garrison:garrisons.add(home)
        group={'tag':'hmb_ai_foot_'+str(index),'kind':'infantry','home':home,'reserve':reserve,
               'garrison':garrison,'mids':[a['mid'] for a in actors]}
        groups.append(group)
        for actor in actors:actor.update(ai_group=group['tag'],ai_role='reserve' if reserve else 'garrison' if garrison else 'assault')
    for kind,roles in [('gun',GUNS),('armor',ARMOR)]:
        actors=[a for a in roster if a['player']==1 and a['kind']=='vehicle' and tactical_role(a) in roles]
        for index,actor in enumerate(actors):
            group={'tag':'hmb_ai_'+kind+'_'+str(index),'kind':kind,'home':index%point_count,
                   'reserve':False,'garrison':False,'mids':[actor['mid']],
                   'rear_support':tactical_role(actor) in REAR_SUPPORT}
            groups.append(group);actor.update(ai_group=group['tag'],ai_role=kind,tactical_role=tactical_role(actor))
    return groups


def support_positions(groups,points,enemy_spawn,bounds,cfg):
    x0,y0,x1,y1=bounds;out={}
    if x1-x0<=300 or y1-y0<=300:raise BridgeError('AI support positions require usable pathing bounds')
    for index,group in enumerate(groups):
        for p,(x,y) in enumerate(points):
            if group.get('rear_support'):
                # Informational only: rear guns receive no waypoint orders.
                out[group['tag'],p]=list(enemy_spawn)
                continue
            dx,dy=enemy_spawn[0]-x,enemy_spawn[1]-y;length=math.hypot(dx,dy)
            dx,dy=(dx/length,dy/length) if length else (0,1)
            back=integer(cfg.get('ai_gun_standoff',600),'AI gun standoff') if group['kind']=='gun' else 200 if group['kind']=='armor' else 0
            lane=((index%3)-1)*(220 if group['kind'] in ('gun','armor') else 80)
            px=x+dx*back-dy*lane;py=y+dy*back+dx*lane
            out[group['tag'],p]=[round(min(x1-150,max(x0+150,px)),2),round(min(y1-150,max(y0+150,py)),2)]
    return out


def build_director(b,cfg,points,groups=None,positions=None):
    from .objectives import node,scalar,variable,compare,if_action,condition,start_trigger,trigger,started_condition
    if groups is None:
        groups=[{'tag':'hmb_ai_column_'+str(i),'kind':'infantry','home':i,'reserve':True,'garrison':False} for i in range(len(points))]
    variables=['hmb_ai_refresh'];initial=[];orders=[];zones=[];waypoints=[]
    enemy_side='defender' if b.get('player_side','attacker')=='attacker' else 'attacker'
    player_side='attacker' if enemy_side=='defender' else 'defender'
    player_owner=1 if player_side=='attacker' else 2
    def selector(tag,zone=None,human=False):
        fields=[scalar('tag',tag),scalar('state','not dead')]
        if zone:fields.append(scalar('zone',zone))
        if human:fields.append(scalar('type','human'))
        return node('selector',*fields)
    def present(tag,zone,op,value):
        return condition('entities',selector(tag,zone),node('count',scalar('op',op),scalar('value',value)))
    for gi,group in enumerate(groups):
        tag=group['tag'];target='hmb_ai_target_'+str(gi);covered='hmb_ai_cover_'+str(gi)
        variables.extend([target,covered])
        rear=group.get('rear_support',False)
        initial.append(node('"actor_state"',selector(tag),scalar('control','AI'),scalar('fire_mode','open'),scalar('move_mode','hold' if rear or (enemy_side=='defender' and group.get('garrison')) else 'free'),
            scalar('return_fire','on'),scalar('weapon_prepare','on'),node('ai_move',scalar('mode','disable' if rear else 'enable')),
            node('movement',scalar('speed','assault' if group['kind']=='infantry' else 'normal'))))
        if rear:continue
        def issue(p):
            name=tag+'_p'+str(p+1) if positions is not None else 'hmb_point_'+str(p+1)
            action=[scalar('type','start'),scalar('waypoint',name)]
            if group['kind']=='infantry':action.append(node('make_squad'))
            return [node('"waypoint"',node('who',scalar('type','actor'),node('actors',scalar('tag',tag),scalar('state','not dead'))),node('action',*action)),
                    variable(target,'=',p+1),variable(covered,'=',0)]
        def move(p):
            zone=tag+'_arrival_'+str(p+1)
            position=positions[tag,p] if positions is not None else points[p]
            zones.append(node('zone "circle"',node('position',str(position[0]),str(position[1]),'0'),scalar('Name',zone),scalar('Radius',220)))
            if positions is not None:waypoints.append(node('"'+tag+'_p'+str(p+1)+'"',node('position',str(position[0]),str(position[1]),'0')))
            # Keep fighting or using cover until the objective changes. Only
            # refresh a stuck/straying group every four planning passes.
            hold=[if_action(compare('hmb_ai_refresh','==',0),if_action(present(tag,zone,'==',0),*issue(p)))]
            if group['kind']=='infantry' and enemy_side!='defender':
                take_cover=node('"actor_to_cover"',selector(tag,zone,True),node('drop','orders'))
                hold.append(if_action(present(tag,zone,'>',0),if_action(compare(covered,'==',0),take_cover,variable(covered,'=',p+1))))
            return node('"switch"',node('"case"',compare(target,'==',p+1),*hold),node('"default"',*issue(p)))
        moves=[move(p) for p in range(len(points))]
        home=group['home'];rotation=[(home+j)%len(points) for j in range(len(points))]
        if group['kind']=='gun' or group.get('garrison'):
            orders.append(moves[home])
        else:
            cases=[]
            if group.get('reserve'):
                cases += [node('"case"',present('hmb_'+player_side,'hmb_point_'+str(p+1),'>',0),moves[p]) for p in rotation]
            else:
                cases += [node('"case"',compare('hmb_point_'+str(home+1)+'_owner','==',owner),moves[home]) for owner in (player_owner,0)]
            cases += [node('"case"',compare('hmb_point_'+str(p+1)+'_owner','==',owner),moves[p]) for owner in (player_owner,0) for p in rotation]
            orders.append(node('"switch"',*cases,node('"default"',moves[home])))
    interval=integer(cfg.get('ai_order_interval_seconds',15),'AI interval')
    planning=[variable('hmb_ai_refresh','+',1),if_action(compare('hmb_ai_refresh','>=',4),variable('hmb_ai_refresh','=',0)),*orders,
              node('"delay"',scalar('time',interval)),start_trigger('hmb_ai_orders')]
    return {'variables':variables,'initial':initial,'zones':zones,'waypoints':waypoints,
            'trigger':trigger('hmb_ai_orders',started_condition(),[if_action(compare('hmb_finished','==',0),*planning)]),
            'report':{'groups':groups,'order_interval_seconds':interval,'stuck_order_refresh_seconds':interval*4,
                      'cover':'attacking infantry seeks cover once; defending garrisons hold their capture sector without cover relocation',
                      'rear_support':'artillery, rocket and self-propelled artillery hold rear firing positions and fire at targets in range; AT/AA move to support positions',
                      'transports':'parked; crew stay linked','stage':'generated; tactical movement and cover need engine verification'}}
