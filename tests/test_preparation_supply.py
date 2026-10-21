import math,tempfile,unittest,re
from pathlib import Path
from bridge.core import BridgeError
from bridge.preparation import deployment_plan,build_boundaries,arrange_deployment
from bridge.ammunition import supply_ratio,ammunition_items,scaled_reserves,audit_ammunition
from bridge.objectives import build_objectives

class PreparationTests(unittest.TestCase):
    def test_large_force_is_repositioned_with_clearance_and_no_dropped_actors(self):
        actors=[]
        for side,vehicles,foot in [('attacker',14,17),('defender',1,45)]:
            for kind,count in [('vehicle',vehicles),('infantry',foot)]:
                for _ in range(count):actors.append({'mid':len(actors)+1,'side':side,'kind':kind})
        positions,plan=arrange_deployment({},actors,[(2114,245),(-2668,35)],[(200,-500),(0,0),(-200,500)],[-2940,-2586,2612,2617],{})
        self.assertEqual(set(positions),{a['mid'] for a in actors})
        project=lambda p:sum((p[i]-plan['origin'][i])*plan['direction'][i] for i in (0,1))
        for a in actors:
            if a['side']=='attacker':self.assertLess(project(positions[a['mid']]),plan['lines'][0]['offset'])
            else:self.assertGreater(project(positions[a['mid']]),plan['lines'][1]['offset'])
        vehicles=[a for a in actors if a['kind']=='vehicle']
        for i,a in enumerate(vehicles):
            for b in vehicles[i+1:]:self.assertGreaterEqual(math.dist(positions[a['mid']],positions[b['mid']])+1e-6,500)

    def test_compact_town_expands_setup_without_losing_units_or_vehicle_spacing(self):
        roster=[]
        for side,vehicles,foot in [('attacker',14,17),('defender',1,45)]:
            for kind,count in [('vehicle',vehicles),('infantry',foot)]:
                for _ in range(count):roster.append({'mid':len(roster)+1,'side':side,'kind':kind})
        for player in ('attacker','defender'):
            positions,plan=arrange_deployment({'player_side':player},roster,
                [(-849.11,-2316.07),(276.95,2504.17)],
                [(-217.35,252.61),(1672.62,-225.71),(-2334.99,737.38)],
                [-2878.65,-2572.77,2704.29,2541.57],{})
            self.assertEqual(len(positions),len(roster))
            self.assertGreater(plan['placement_search']['extra_depth'],0)
            project=lambda p:sum((p[i]-plan['origin'][i])*plan['direction'][i] for i in (0,1))
            for a in roster:
                depth=project(positions[a['mid']])
                if a['side']=='attacker':self.assertLess(depth,plan['lines'][0]['offset'])
                else:self.assertGreater(depth,plan['lines'][1]['offset'])
            vehicles=[positions[a['mid']] for a in roster if a['kind']=='vehicle']
            for i,a in enumerate(vehicles):
                for b in vehicles[i+1:]:self.assertGreaterEqual(math.dist(a,b)+1e-6,500)

    def test_defending_ai_starts_near_objectives_with_crews_and_rear_guns_preserved(self):
        from bridge.preparation import position_defending_ai
        roster=[{'mid':1,'side':'attacker','player':0,'kind':'infantry'},
            {'mid':2,'side':'defender','player':1,'kind':'vehicle','role':'light_tank','ai_group':'armor'},
            {'mid':3,'side':'defender','player':1,'kind':'infantry','ai_group':'foot'},
            {'mid':4,'side':'defender','player':1,'kind':'vehicle','role':'artillery'},
            {'mid':5,'side':'defender','player':1,'kind':'crew','parent_mid':2}]
        old={1:[-2000,0],2:[2200,-700],3:[2200,700],4:[2600,1400],5:[2200,-700]}
        points=[[0,-700],[0,700]]
        plan={'origin':[-2000,0],'direction':[1,0],'lines':[{'side':'defender','offset':1550}]}
        groups=[{'tag':'armor','home':0},{'tag':'foot','home':1}]
        out,report=position_defending_ai({},roster,old,points,[-3000,-2000,3000,2000],plan,groups,{})
        self.assertEqual(set(out),set(old));self.assertEqual(old[2],[2200,-700])
        self.assertLess(math.dist(out[2],points[0]),math.dist(old[2],points[0]))
        self.assertLessEqual(math.dist(out[3],points[1]),300)
        self.assertLess(min(math.dist(out[4],p) for p in points),min(math.dist(old[4],p) for p in points))
        self.assertGreater(min(math.dist(out[4],p) for p in points),math.dist(out[2],points[0]))
        self.assertEqual(out[1],old[1])
        self.assertEqual(out[5],out[2]);self.assertEqual(len(report['moved']),3)
        for mid in (2,3):self.assertGreater(out[mid][0],-450)
        self.assertGreaterEqual(math.dist(out[2],out[3]),310)
        human,report=position_defending_ai({'player_side':'defender'},roster,old,points,[-3000,-2000,3000,2000],plan,groups,{})
        self.assertEqual(human,old);self.assertFalse(report['enabled'])

    def plan(self):
        actors=[{'mid':1,'side':'attacker'},{'mid':2,'side':'defender'},{'mid':3,'side':'attacker','parent_mid':1}]
        positions={1:(-2000,0),2:(2000,0),3:(-2000,0)}
        return deployment_plan(actors,positions,[(0,-300),(0,300)],[-3000,-2000,3000,2000])

    def test_asymmetric_lines_leave_capture_areas_to_defenders_and_include_spawns(self):
        p=self.plan();project=lambda xy:sum((xy[i]-p['origin'][i])*p['direction'][i] for i in (0,1))
        attack,defend=p['lines']
        self.assertLess(project((-2000,0)),attack['offset'])
        self.assertLess(attack['offset'],defend['offset'])
        self.assertGreater(project((2000,0)),defend['offset'])
        self.assertGreater(project((0,0))-p['capture_radius'],defend['offset'])
        for line in p['lines']:
            for end in line['ends']:self.assertAlmostEqual(project(end),line['offset'])

    def test_overlapping_deployment_fails_instead_of_trapping_a_force(self):
        with self.assertRaises(BridgeError):deployment_plan([{'mid':1,'side':'attacker'},{'mid':2,'side':'defender'}],{1:(0,0),2:(1000,0)},[(100,0)],[-2000,-2000,2000,2000])

    def test_obstacle_rotation_uses_native_mission_xform_syntax(self):
        barrier=build_boundaries(self.plan())
        entities=[row for row in barrier['entities'] if row.startswith('{Entity "obstacle"')]
        self.assertTrue(entities)
        for row in entities:
            self.assertNotIn('{Orientation',row)
            match=re.search(r'\{xform zl (-?[0-9.]+)\}',row)
            self.assertIsNotNone(match)
            self.assertAlmostEqual(float(match[1]),90)

    def test_preparation_wall_resources_cover_arcs_and_do_not_accumulate_damage(self):
        import zipfile
        from bridge.preparation import write_boundary_resources,BARRIER_HEIGHT
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'resource/entity').mkdir(parents=True)
            native='{Skeleton {bone "dummy02"}} {Volume "roof_vol01" {Box 393.701 500.701 15.90551} {Bone "dummy02"} {Matrix34 1 0 0 0 0 1 0 -1 0 0 -2.95276 196.29}}'
            with zipfile.ZipFile(root/'resource/entity/e1.pak','w') as z:z.writestr('service/invisible_wall/invisible_wall.mdl',native)
            write_boundary_resources(root/'mod',{'mow':str(root)})
            path=root/'mod/resource/entity/service/hmb_prep_vehicle_wall'
            definition=(path/'hmb_prep_vehicle_wall.def').read_text(encoding='utf8')
            model=(path/'hmb_prep_vehicle_wall.mdl').read_text(encoding='utf8')
            self.assertIn('construction.inc',definition)
            self.assertIn('{obstacleID "unbreakable"}',definition)
            self.assertIn('("armor_disable_damage_acc")',definition)
            self.assertIn('{bullet 1} {contact 1} {obstacle 1}',definition)
            height=float(re.search(r'\{Box 393.701 ([0-9.]+)',model)[1])
            center=float(re.search(r'0 -2.95276 ([0-9.]+)',model)[1])
            self.assertEqual(height,BARRIER_HEIGHT)
            self.assertEqual(center-height/2,-54)
            self.assertGreater(center+height/2,19000)
            self.assertIn('{Extent 196.8505 24}',model)

    def test_vehicle_walls_overlap_enable_contact_and_share_release_tag(self):
        from native_trial.deployment_supply_probe import boundary_counts
        barrier=build_boundaries(self.plan())
        rows=barrier['entities'];walls=[row for row in rows if row.startswith('{Entity "hmb_prep_vehicle_wall"')]
        self.assertEqual(len(walls),barrier['report']['vehicle_contact_walls'])
        self.assertTrue(walls)
        positions=[]
        for row in walls:
            self.assertIn('{Volume "roof_vol01" {able clear {visible 0} {bullet 1} {contact 1}}}',row)
            uid=re.search(r'hmb_prep_vehicle_wall" (0x[0-9a-f]+)',row)[1]
            self.assertIn('{Tags "hmb_prep_boundary" "hmb_prep_vehicle_wall" '+uid+'}',rows)
            positions.append(tuple(map(float,re.search(r'\{Position ([^}]+)',row)[1].split())))
        half=len(positions)//2
        for line in (positions[:half],positions[half:]):
            for a,b in zip(line,line[1:]):self.assertLessEqual(math.dist(a,b),350.001)
        counts=boundary_counts(' '.join(rows))
        self.assertEqual(counts['vehicle_walls'],len(walls))

    def test_barriers_are_mission_entities_and_removed_before_combat_begins(self):
        barrier=build_boundaries(self.plan())
        self.assertGreater(barrier['report']['navigation_obstacles'],0)
        self.assertIn('Entity "obstacle"',' '.join(barrier['entities']))
        self.assertIn('Entity "flagstaff"',' '.join(barrier['entities']))
        objectives=build_objectives({'id':'a'*32},{'preparation_seconds':60},[(0,0)],preparation_release=barrier['release'])
        start=next(t for t in objectives['triggers'] if t.startswith('{"hmb_prepare"'))
        self.assertLess(start.index('"delete"'),start.index('hmb_preparation_released$'))
        self.assertLess(start.index('"delete"'),start.index('hmb_battle_started$'))

class SupplyTests(unittest.TestCase):
    def test_native_audit_uses_runtime_uid_and_sums_split_stacks(self):
        actor={'mid':1,'ammunition':{'items':[{'identity':['rifle','ammo'],'reserve':25}]}}
        native='{mission {Human "mp/ger/rifle" 0x4 {MID 1}} {Inventory 0x4 {box {item "rifle" "ammo" 10} {item "rifle" "ammo" 15}}}}'
        self.assertEqual(audit_ammunition([actor],native)['actors_checked'],1)
        with self.assertRaises(BridgeError):audit_ammunition([actor],native.replace('"ammo" 15','"ammo" 100'))

    def test_saved_percentages_have_unambiguous_units_and_unknown_is_not_full_supply(self):
        self.assertEqual(supply_ratio({'supply_raw':'50'}),.5)
        self.assertEqual(supply_ratio({'supply_raw':'0.5'}),.005)
        self.assertIsNone(supply_ratio({}))
        for raw in ('nan','-1','oops'):
            with self.assertRaises(BridgeError):supply_ratio({'supply_raw':raw})

    def test_native_inventory_preserves_weapons_tools_and_only_scales_reserves(self):
        text='{breed {inventory {item "mauzer" filled} {item "ammo rifle" 100} {item "rifle" "ammo" 25} {item "grenade m24" 2} {item "bandage" 3}}}'
        items=ammunition_items(text)
        self.assertEqual(items,[{'identity':['rifle','ammo'],'native_reserve':125},{'identity':['m24','grenade'],'native_reserve':2}])
        factor,reserves=scaled_reserves(items,.5,.5)
        self.assertEqual(factor,.25);self.assertEqual([i['reserve'] for i in reserves],[32,1])
        self.assertNotIn('mauzer',str(reserves));self.assertNotIn('bandage',str(reserves))

    def test_vehicle_ap_he_and_machine_gun_reserves_remain_distinct(self):
        text='{game_entity {extender "inventory" {box {item "bullet45 ap" 35} {item "ammo bullet45 fg" 30} {item "ammo mgun" 1850}}} {Weaponry {place "gun" {weapon "45mm_20k" filled}}}}'
        items=ammunition_items(text,True)
        self.assertEqual([i['identity'] for i in items],[['bullet45','ap','ammo'],['bullet45','fg','ammo'],['mgun','ammo']])
        _,reserves=scaled_reserves(items,0,0)
        self.assertEqual([i['reserve'] for i in reserves],[7,6,370])
        _,normal=scaled_reserves(items,None,None)
        self.assertEqual([i['reserve'] for i in normal],[35,30,1850])
