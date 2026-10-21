import unittest,tempfile,zipfile
from pathlib import Path
from bridge.equipment import allocate_models,vehicle_equivalent,distribute_equipment
from bridge.gem import formation_positions,blocks,inline_breed_includes
from bridge.core import BridgeError
from bridge.objectives import build_objectives

class EquipmentTests(unittest.TestCase):
    def test_moved_breed_resolves_includes_from_original_native_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'gamelogic.pak'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('set/breed/mp/ger/veterancy_generic.inc','(define "veterancy_1" {"lvl_1" 4})')
            with zipfile.ZipFile(path) as z:
                text=inline_breed_includes('{breed {veterancy (include "veterancy_generic.inc") ("veterancy_1")}}','set/breed/mp/ger/rifle.set',z)
                self.assertNotIn('(include',text)
                self.assertIn('(define "veterancy_1"',text)
                list(blocks(text))
                with self.assertRaises(BridgeError): inline_breed_includes('(include "missing.inc")','set/breed/mp/ger/rifle.set',z)

    def test_mixed_stock_is_preserved_even_below_actor_target(self):
        items=[{'variant_id':'old','represented_amount':90},{'variant_id':'new','represented_amount':10}]
        self.assertEqual([e['variant_id'] for e in allocate_models(items,10)].count('old'),9)
        self.assertEqual({e['variant_id'] for e in allocate_models(items,1)},{'old','new'})

    def test_generation_selects_native_tank_without_reading_campaign_date(self):
        self.assertEqual(vehicle_equivalent('ger','light_tank',{'model':'light_tank_chassis_1'},'fallback')[0],'pz1b')
        self.assertEqual(vehicle_equivalent('ger','light_tank',{'model':'light_tank_chassis_3'},'fallback')[0],'pz2l')
        self.assertIn('approximation',vehicle_equivalent('jap','light_tank',{'model':'light_tank_chassis_3'},'fallback')[1])

    def test_destroyed_new_tank_only_represents_new_equipment(self):
        own=[{'kind':'vehicle','equipment_variant_id':v,'primary_families':['light_tank_chassis'],'represented_equipment':[]} for v in ('old','new','new')]
        items=[{'variant_id':v,'represented_amount':amount} for v,amount in [('old',60),('new',90)]]
        distribute_equipment(own,[],'light_tank_chassis',items)
        self.assertEqual(own[0]['represented_equipment'],[{'variant_id':'old','family':'light_tank_chassis','amount':60}])
        self.assertEqual(own[1]['represented_equipment'][0]['amount'],45)
        self.assertEqual(own[1]['represented_equipment'][0]['variant_id'],'new')

    def test_vehicle_grid_has_clearance_from_vehicles_and_foot(self):
        roster=[{'player':0,'mid':i+1,'kind':'vehicle'} for i in range(8)]+[{'player':0,'mid':i+9,'kind':'infantry'} for i in range(20)]
        pos=formation_positions(roster,[[0,0],[0,0]],[-5000,-5000,5000,5000])
        for a in roster[:8]:
            for b in roster:
                if a==b: continue
                self.assertGreaterEqual(sum((pos[a['mid']][i]-pos[b['mid']][i])**2 for i in (0,1)),500**2)

    def test_clock_selects_score_winner_and_defender_on_tie(self):
        objectives=build_objectives({'id':'fixture','player_side':'attacker'},{},[[0,0],[100,200]])
        text=' '.join(objectives['triggers'])
        list(blocks('{mission '+text+'}'))
        self.assertEqual(objectives['rules']['time_limit_seconds'],900)
        self.assertIn('hmb_timeout_winner$',text)
        self.assertIn('hmb_score_lead$',text)
        self.assertIn('{op ">="} {value 100}',text)
        self.assertIn('{count {op ">"} {value 0}}',text)
        self.assertNotIn('{op ">>"}',text)
        self.assertIn('{waypoint "hmb_point_2"}',text)
        self.assertIn('{move_mode "free"}',text)
    def test_preparation_gates_ai_scoring_clock_and_all_endings(self):
        objectives=build_objectives({'id':'fixture'},{},[[0,0]])
        self.assertEqual(objectives['rules']['preparation_seconds'],60)
        by_name={block.split('"',2)[1]:block for block in objectives['triggers']}
        prepare=by_name['hmb_prepare']
        self.assertIn('{"delay" {time 60}}',prepare)
        self.assertIn('{var "hmb_battle_started$"} {op "="} {value 1}',prepare)
        for name in ('hmb_clock','hmb_ai_orders','hmb_point_1_tick','hmb_score_win_attacker','hmb_time_win_defender'):
            condition=list(blocks(by_name[name][1:-1]))[0]
            self.assertIn('{var "hmb_battle_started$"} {op "=="} {value 1}',condition)
        self.assertIn('{"timer" {time 900}',by_name['hmb_clock'])

if __name__=='__main__': unittest.main()
