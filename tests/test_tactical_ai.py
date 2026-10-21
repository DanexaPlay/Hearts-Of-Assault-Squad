import copy,unittest
from bridge.tactical_ai import assign_groups,support_positions
from bridge.objectives import build_objectives
from bridge.gem import blocks
from bridge.core import BridgeError


class TacticalAITests(unittest.TestCase):
    def force(self):
        actors=[{'mid':i+1,'player':1,'kind':'infantry','division_index':0,'component_index':0,'represented_manpower':200} for i in range(48)]
        for role in ('light_tank','medium_tank','recon','artillery','anti_tank','motorized'):
            parent=len(actors)+1
            actors.append({'mid':parent,'player':1,'kind':'vehicle','role':role,'represented_manpower':0})
            actors.append({'mid':parent+1,'player':1,'kind':'crew','parent_mid':parent,'represented_manpower':100})
        actors.append({'mid':len(actors)+1,'player':0,'kind':'infantry','represented_manpower':200})
        return actors

    def test_squads_reserves_and_vehicle_roles_preserve_force_and_crews(self):
        roster=self.force();before=copy.deepcopy(roster);groups=assign_groups(roster,3,{})
        foot=[g for g in groups if g['kind']=='infantry']
        self.assertEqual(len(foot),8);self.assertTrue(all(len(g['mids'])==6 for g in foot))
        self.assertEqual(sum(g['reserve'] for g in foot),2)
        self.assertEqual({g['home'] for g in foot if g['garrison']},{0,1,2})
        self.assertEqual(sum(g['kind']=='gun' for g in groups),2)
        self.assertEqual(sum(g['kind']=='armor' for g in groups),3)
        self.assertEqual(sum(a['represented_manpower'] for a in before),sum(a['represented_manpower'] for a in roster))
        assigned=[mid for g in groups for mid in g['mids']]
        self.assertEqual(len(assigned),len(set(assigned)))
        for actor in roster:
            if actor['kind']=='crew' or actor['player']==0 or actor.get('role')=='motorized':self.assertNotIn('ai_group',actor)

    def test_small_defense_assigns_all_three_points_and_never_seeks_distant_cover(self):
        roster=[{'mid':i+1,'player':1,'kind':'infantry','division_index':0} for i in range(9)]
        groups=assign_groups(roster,3,{},defending=True)
        self.assertEqual(len(groups),3)
        self.assertEqual({g['home'] for g in groups if g['garrison']},{0,1,2})
        self.assertEqual(sorted(mid for g in groups for mid in g['mids']),list(range(1,10)))
        points=[[0,0],[1500,0],[0,1500]]
        positions=support_positions(groups,points,[0,3500],[-4000,-4000,4000,4000],{})
        obj=build_objectives({'id':'fixture','player_side':'attacker'},{},points,groups,positions)
        orders=next(t for t in obj['triggers'] if t.startswith('{"hmb_ai_orders"'))
        prep=next(t for t in obj['triggers'] if t.startswith('{"hmb_prepare"'))
        self.assertNotIn('"actor_to_cover"',orders)
        self.assertEqual(prep.count('{move_mode "hold"}'),3)
        # Garrison choices do not rotate to other points after capturing home.
        for g in groups:
            self.assertIn(g['tag']+'_p'+str(g['home']+1),orders)

    def test_different_divisions_do_not_merge_into_a_squad(self):
        roster=[{'mid':i+1,'player':1,'kind':'infantry','division_index':i//5} for i in range(10)]
        groups=assign_groups(roster,3,{})
        self.assertEqual(len(groups),2)
        self.assertTrue(all(len({roster[mid-1]['division_index'] for mid in g['mids']})==1 for g in groups))
        with self.assertRaises(BridgeError):assign_groups(roster,3,{'ai_squad_size':13})

    def test_support_positions_stay_in_map_and_guns_follow_behind_armor(self):
        groups=assign_groups(self.force(),3,{})
        points=[[0,0],[3800,3900],[-3900,-3800]];bounds=[-4000,-4000,4000,4000]
        positions=support_positions(groups,points,[0,3500],bounds,{})
        for x,y in positions.values():self.assertTrue(-3850<=x<=3850 and -3850<=y<=3850)
        gun=next(g for g in groups if g['kind']=='gun' and not g['rear_support']);armor=next(g for g in groups if g['kind']=='armor')
        self.assertGreater(positions[gun['tag'],0][1],positions[armor['tag'],0][1])

    def test_ai_initializes_once_uses_cover_and_keeps_guns_out_of_infantry_squads(self):
        groups=assign_groups(self.force(),3,{})
        points=[[0,0],[1500,0],[0,1500]]
        positions=support_positions(groups,points,[0,3500],[-4000,-4000,4000,4000],{})
        obj=build_objectives({'id':'fixture','player_side':'defender'},{},points,groups,positions)
        by_name={t.split('"',2)[1]:t for t in obj['triggers']};orders=by_name['hmb_ai_orders']
        self.assertIn('"actor_state"',by_name['hmb_prepare'])
        self.assertNotIn('"actor_state"',orders)
        self.assertIn('"actor_to_cover"',orders);self.assertIn('{type "human"}',orders)
        self.assertIn('hmb_ai_refresh$',orders)
        self.assertEqual(obj['ai']['stuck_order_refresh_seconds'],60)
        gun=next(g for g in groups if g['kind']=='gun' and not g['rear_support'])
        commands=[]
        def visit(text):
            for block in blocks(text):
                if block.startswith('{"waypoint"') and '{tag "'+gun['tag']+'"}' in block:commands.append(block)
                visit(block[1:-1])
        visit(orders)
        self.assertTrue(commands);self.assertTrue(all('{make_squad}' not in command for command in commands))
        list(blocks('{mission '+orders+'}'))
        self.assertEqual(len(obj['zones']),len(points)*(sum(not g.get('rear_support') for g in groups)+1))

    def test_zis3_maneuvers_as_at_without_changing_hoi4_equipment_role(self):
        roster=[{'mid':1,'player':1,'kind':'vehicle','role':'artillery','entity':'zis3'}]
        groups=assign_groups(roster,3,{},defending=True)
        self.assertEqual(roster[0]['role'],'artillery')
        self.assertEqual(roster[0]['tactical_role'],'anti_tank')
        self.assertFalse(groups[0]['rear_support'])
        points=[[0,0],[1500,0],[0,1500]]
        positions=support_positions(groups,points,[0,3500],[-4000,-4000,4000,4000],{})
        obj=build_objectives({'id':'fixture','player_side':'attacker'},{},points,groups,positions)
        orders=next(t for t in obj['triggers'] if t.startswith('{"hmb_ai_orders"'))
        self.assertIn(groups[0]['tag'],orders)
        self.assertIn('"waypoint"',orders)

    def test_artillery_holds_rear_while_at_and_aa_receive_movement_orders(self):
        roster=[{'mid':i+1,'player':1,'kind':'vehicle','role':role} for i,role in enumerate(
            ['artillery','rocket','sp_artillery','anti_tank','anti_air','sp_anti_air'])]
        groups=assign_groups(roster,3,{})
        points=[[0,0],[1500,0],[0,1500]]
        positions=support_positions(groups,points,[0,3500],[-4000,-4000,4000,4000],{})
        obj=build_objectives({'id':'fixture'},{},points,groups,positions)
        prep=next(t for t in obj['triggers'] if t.startswith('{"hmb_prepare"'))
        orders=next(t for t in obj['triggers'] if t.startswith('{"hmb_ai_orders"'))
        for g in groups:
            if g['rear_support']:
                self.assertNotIn(g['tag'],orders)
                self.assertEqual(positions[g['tag'],0],[0,3500])
                self.assertIn('{tag "'+g['tag']+'"}',prep)
            else:self.assertIn(g['tag'],orders)
        self.assertEqual(prep.count('{move_mode "hold"}'),3)
        self.assertEqual(prep.count('{ai_move {mode "disable"}}'),3)
