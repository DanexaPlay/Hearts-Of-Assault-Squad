"""Deployment barriers: native navigation plus a dedicated vehicle collider.

Engine behaviour (including direct control) requires a live rehearsal. This
does not modify a map slot's cached geometry. A stable helper definition must
be registered once by a cold engine launch.
"""
import math
from .core import BridgeError
from .archives import open_archive

def segment_in_bounds(origin,direction,offset,bounds):
    ux,uy=direction;px,py=origin[0]+ux*offset,origin[1]+uy*offset
    tx,ty=-uy,ux;x0,y0,x1,y1=bounds;hits=[]
    for axis,value in ((0,x0),(0,x1),(1,y0),(1,y1)):
        denominator=(tx,ty)[axis]
        if abs(denominator)<1e-9:continue
        s=(value-(px,py)[axis])/denominator;q=(px+s*tx,py+s*ty)
        if x0-1e-6<=q[0]<=x1+1e-6 and y0-1e-6<=q[1]<=y1+1e-6 and all(math.dist(q,h)>1e-5 for h in hits):hits.append(q)
    if len(hits)!=2:raise BridgeError('Preparation boundary does not cross the playable rectangle')
    return hits

def deployment_plan(roster,positions,points,bounds,radius=300):
    primary={side:[positions[a['mid']] for a in roster if a['side']==side and not a.get('parent_mid')] for side in ('attacker','defender')}
    if not all(primary.values()) or not points:raise BridgeError('Preparation boundaries require both armies and capture points')
    center={side:[sum(p[j] for p in values)/len(values) for j in (0,1)] for side,values in primary.items()}
    origin=center['attacker'];distance=math.dist(origin,center['defender'])
    if distance<1:raise BridgeError('Preparation sides have overlapping spawn centres')
    direction=[(center['defender'][j]-origin[j])/distance for j in (0,1)]
    project=lambda p:sum((p[j]-origin[j])*direction[j] for j in (0,1))
    attacker=max(map(project,primary['attacker']))+150
    defender=min(map(project,points))-radius-150
    if defender-attacker<100 or min(map(project,primary['defender']))<=defender+75:
        raise BridgeError('Formation is too close to objectives for safe preparation boundaries')
    lines=[]
    for side,offset in [('attacker',attacker),('defender',defender)]:
        ends=segment_in_bounds(origin,direction,offset,bounds)
        lines.append({'side':side,'offset':offset,'ends':[list(p) for p in ends]})
    return {'origin':origin,'direction':direction,'lines':lines,'capture_radius':radius,
            'attacker_rule':'stay behind spawn-side line','defender_rule':'capture areas are inside defender deployment zone'}

def _arrange_deployment(b,roster,spawns,points,bounds,cfg):
    """Fit complete forces in their own half-planes, with vehicle clearances.

    Used when the previous rectangular formation would straddle a boundary.
    Native terrain/pathfinding still needs live inspection at these positions.
    """
    attacker_player=0 if b.get('player_side','attacker')=='attacker' else 1
    origin=spawns[attacker_player];enemy=spawns[1-attacker_player];distance=math.dist(origin,enemy)
    if distance<1:raise BridgeError('No distinct deployment spawn points')
    u=[(enemy[i]-origin[i])/distance for i in (0,1)];t=[-u[1],u[0]]
    projection=lambda p,axis:sum((p[i]-origin[i])*axis[i] for i in (0,1))
    radius=cfg.get('capture_radius',300);defender=min(projection(p,u) for p in points)-radius-150
    attacker=min(600+cfg.get('_deployment_extra_depth',0),defender-100)
    if attacker<150:raise BridgeError('Capture points are too close to the attacking spawn for deployment')
    x0,y0,x1,y1=bounds;corners=[(x,y) for x in (x0,x1) for y in (y0,y1)]
    depths=[projection(p,u) for p in corners];widths=[projection(p,t) for p in corners]
    positions={};placed=[]
    for side,spawn in [('attacker',origin),('defender',enemy)]:
        for vehicle in (True,False):
            actors=[a for a in roster if a['side']==side and not a.get('parent_mid') and (a['kind']=='vehicle')==vehicle]
            spacing=cfg.get('vehicle_spawn_spacing',500) if vehicle else cfg.get('infantry_spawn_spacing',140)
            if not isinstance(spacing,(int,float)) or spacing<100:raise BridgeError('Unsafe deployment spacing')
            clearance=(spacing-20)/2
            candidates=[]
            edge=attacker-clearance-50 if side=='attacker' else defender+clearance+50
            extent=edge-min(depths) if side=='attacker' else max(depths)-edge
            for di in range(max(0,math.ceil(extent/spacing))+1):
                d=edge-di*spacing if side=='attacker' else edge+di*spacing
                for ti in range(math.floor(min(widths)/spacing),math.ceil(max(widths)/spacing)+1):
                    across=(ti+cfg.get('_deployment_grid_phase',0))*spacing;p=[origin[i]+u[i]*d+t[i]*across for i in (0,1)]
                    if x0+clearance+40<=p[0]<=x1-clearance-40 and y0+clearance+40<=p[1]<=y1-clearance-40:candidates.append(p)
            candidates.sort(key=lambda p:math.dist(p,spawn))
            for actor in actors:
                index=next((i for i,p in enumerate(candidates) if all(math.dist(p,q)+1e-6>=clearance+r+20 for q,r in placed)),None)
                if index is None:raise BridgeError('Complete force cannot fit safely inside its preparation zone')
                p=candidates.pop(index);positions[actor['mid']]=p;placed.append((p,clearance))
    for actor in roster:
        if actor.get('parent_mid'):positions[actor['mid']]=positions[actor['parent_mid']]
    plan={'origin':origin,'direction':u,'capture_radius':radius,'layout_adapted':True,
          'attacker_rule':'stay behind spawn-side line','defender_rule':'capture areas are inside defender deployment zone',
          'lines':[{'side':side,'offset':offset,'ends':[list(p) for p in segment_in_bounds(origin,u,offset,bounds)]}
                   for side,offset in [('attacker',attacker),('defender',defender)]]}
    return positions,plan


def arrange_deployment(b,roster,spawns,points,bounds,cfg):
    # Keep the near-spawn line where possible. On smaller maps, allow the
    # complete force extra setup depth before the defenders' objective line;
    # never shrink vehicle clearance or drop a battalion representation.
    last=None
    for extra in (0,200,400,800,1600,3200):
        for phase in (0,.5,.25,.75):
            try:
                positions,plan=_arrange_deployment(b,roster,spawns,points,bounds,
                    {**cfg,'_deployment_extra_depth':extra,'_deployment_grid_phase':phase})
                plan['placement_search']={'extra_depth':extra,'grid_phase':phase}
                return positions,plan
            except BridgeError as e:
                if str(e)!='Complete force cannot fit safely inside its preparation zone':raise
                last=e
    raise last


def position_defending_ai(b,roster,positions,points,bounds,plan,groups,cfg):
    """Seed defending combat groups by their objective; retain rear support.

    Uses verified capture anchors, bounding rectangle and deployment half-plane.
    Static buildings, slopes and water still need native gameplay verification.
    """
    if b.get('player_side','attacker')!='attacker' or not points:
        return positions,{'enabled':False}
    from .tactical_ai import REAR_SUPPORT,tactical_role
    own=[a for a in roster if a['side']=='defender' and a['player']==1 and not a.get('parent_mid')]
    moving=[a for a in own if a['kind']=='infantry' or
            (a['kind']=='vehicle' and a.get('role')!='motorized')]
    if not moving:return positions,{'enabled':False}
    origin=plan['origin'];u=plan['direction']
    line=next(x['offset'] for x in plan['lines'] if x['side']=='defender')
    project=lambda p:sum((p[i]-origin[i])*u[i] for i in (0,1))
    group_map={g['tag']:g for g in groups};out={mid:list(p) for mid,p in positions.items()}
    primary=[a for a in roster if not a.get('parent_mid')]
    radius=lambda a:((cfg.get('vehicle_spawn_spacing',500) if a['kind']=='vehicle' else cfg.get('infantry_spawn_spacing',140))-20)/2
    x0,y0,x1,y1=bounds;changes=[]
    moving.sort(key=lambda a:(a['kind']!='vehicle',a['mid']))
    for index,actor in enumerate(moving):
        group=group_map.get(actor.get('ai_group'),{});home=group.get('home',index%len(points))
        rear=tactical_role(actor) in REAR_SUPPORT
        setback=cfg.get('ai_rear_gun_standoff',1200) if rear else 400 if actor['kind']=='vehicle' else 450 if group.get('reserve') else 120
        target=[points[home][i]+u[i]*setback for i in (0,1)]
        clearance=radius(actor);spacing=clearance*2+20
        candidates=[]
        for xi in range(math.floor((x0+clearance+40-target[0])/spacing),math.ceil((x1-clearance-40-target[0])/spacing)+1):
            for yi in range(math.floor((y0+clearance+40-target[1])/spacing),math.ceil((y1-clearance-40-target[1])/spacing)+1):
                p=[target[0]+xi*spacing,target[1]+yi*spacing]
                if not (x0+clearance+40<=p[0]<=x1-clearance-40 and y0+clearance+40<=p[1]<=y1-clearance-40):continue
                if project(p)<line+clearance+50:continue
                if math.dist(p,target)>=math.dist(out[actor['mid']],target):continue
                candidates.append(p)
        candidates.sort(key=lambda p:math.dist(p,target))
        chosen=next((p for p in candidates if all(a['mid']==actor['mid'] or math.dist(p,out[a['mid']])+1e-6>=clearance+radius(a)+20 for a in primary)),None)
        if chosen is not None:
            before=out[actor['mid']];out[actor['mid']]=chosen
            changes.append({'mid':actor['mid'],'home':home,'from':before,'to':chosen})
    for actor in roster:
        if actor.get('parent_mid'):out[actor['mid']]=list(out[actor['parent_mid']])
    return out,{'enabled':True,'moved':changes,'rear_support':'artillery, rockets and self-propelled artillery deploy to rear firing positions; transport stays at spawn',
        'stage':'geometry checked; native terrain occupancy verification pending'}


VEHICLE_WALL='hmb_prep_vehicle_wall'
BARRIER_HEIGHT=20000

def write_boundary_resources(dest,cfg):
    """Invisible native wall geometry, construction collider, uncrushable pathing.

    Native invisible_wall defaults to collider "nothing" (noContactsAtAll).
    A mission volume override cannot change that definition-level profile.
    """
    import zipfile,re
    from pathlib import Path
    folder=Path(dest)/'resource/entity/service/hmb_prep_vehicle_wall'
    folder.mkdir(parents=True,exist_ok=True)
    with open_archive(Path(cfg['mow'])/'resource/entity/e1.pak') as z:
        model=z.read('service/invisible_wall/invisible_wall.mdl').decode('utf-8-sig')
    # The native model rotates its second box axis upright. Extend that
    # axis and raise its centre while preserving a 54-unit overlap below
    # local ground. This closes the artillery arc loophole during setup.
    model,count=re.subn(r'\{Box 393\.701 500\.701 15\.90551\}',
                       '{Box 393.701 '+str(BARRIER_HEIGHT)+' 15.90551}',model)
    if count!=1:raise BridgeError('Native preparation wall volume changed')
    model,count=re.subn(r'0\s+-2\.95276\s+196\.29',
                       '0 -2.95276 '+str(BARRIER_HEIGHT/2-54),model)
    if count!=1:raise BridgeError('Native preparation wall transform changed')
    # Native obstacle syntax from service/obstacle/obstacle.mdl. Match the
    # wall width, with overlap between neighbouring segments at 350 units.
    model+='\n{Obstacle "deployment" {Obb2 {Center 0 0} {Extent 196.8505 24} {Axis -1 0}} {Rotate}}\n'
    definition='''{game_entity
 (include "/properties/construction.inc")
 {Extension "hmb_prep_vehicle_wall.mdl"}
 {obstacleID "unbreakable"}
 ("armor_disable_damage_acc")
 {Volume "roof_vol01"
  {Tags "body"} {Thickness 50}
  {able clear {visible 0} {bullet 1} {contact 1} {obstacle 1}}
 }
 {volume defaultmaterial "dummy"}
}
'''
    (folder/'hmb_prep_vehicle_wall.def').write_text(definition,encoding='utf8')
    (folder/'hmb_prep_vehicle_wall.mdl').write_text(model,encoding='utf8')

def build_boundaries(plan):
    from .objectives import node,scalar
    rows=[];obstacles=0;flags=0;walls=0
    for line in plan['lines']:
        a,b=line['ends'];length=math.dist(a,b);steps=max(1,math.ceil(length/30))
        # Shipped map/multi/1v1_argentan/map uses {xform zl degrees}.
        # Orientation is a matrix field, not a three-angle mission transform.
        yaw=math.degrees(math.atan2(b[1]-a[1],b[0]-a[0]))
        for i in range(steps+1):
            x=a[0]+(b[0]-a[0])*i/steps;y=a[1]+(b[1]-a[1])*i/steps
            uid=hex(0xfd000+obstacles);obstacles+=1
            rows+=[node('Entity "obstacle" '+uid,node('Position',f'{x:.3f}',f'{y:.3f}'),node('xform zl',f'{yaw:.4f}')),
                   node('Tags "hmb_prep_boundary" "hmb_prep_'+line['side']+'" '+uid)]
        # Native invisible_wall has a 393.701-wide upright contact volume.
        # Dedicated definition enables the construction collider and unbreakable pathing.
        # Navigation obstacles alone proved permeable to tracked vehicles.
        wall_steps=max(1,math.ceil(length/350))
        for i in range(wall_steps+1):
            x=a[0]+(b[0]-a[0])*i/wall_steps;y=a[1]+(b[1]-a[1])*i/wall_steps
            uid=hex(0xfb000+walls);walls+=1
            rows+=[node('Entity "'+VEHICLE_WALL+'" '+uid,
                       node('Position',f'{x:.3f}',f'{y:.3f}'),node('xform zl',f'{yaw:.4f}'),
                       node('Volume "roof_vol01"',node('able clear',node('visible','0'),node('bullet','1'),node('contact','1')))),
                   node('Tags "hmb_prep_boundary" "hmb_prep_vehicle_wall" '+uid)]
        marks=max(1,math.ceil(length/350))
        for i in range(marks+1):
            x=a[0]+(b[0]-a[0])*i/marks;y=a[1]+(b[1]-a[1])*i/marks
            uid=hex(0xfc000+flags);flags+=1
            rows+=[node('Entity "flagstaff" '+uid,node('Position',f'{x:.3f}',f'{y:.3f}')),
                   node('Tags "hmb_prep_boundary" "hmb_prep_marker" '+uid)]
    if obstacles>=4096 or flags>=4096 or walls>=4096:raise BridgeError('Preparation barrier exceeds its entity namespace')
    remove=node('"delete"',node('selector',scalar('tag','hmb_prep_boundary')))
    return {'entities':rows,'release':[remove],'report':{**plan,'navigation_obstacles':obstacles,'visible_markers':flags,'vehicle_contact_walls':walls,'projectile_barrier_height':BARRIER_HEIGHT,
        'projectile_enforcement':'tall bullet-enabled volume; native artillery verification pending',
        'stage':'movement/projectile barrier verified in native trial; game_entity flagstaff marker release awaits engine verification'}}
