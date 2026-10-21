import unittest,tempfile,zipfile
from pathlib import Path
from bridge.formations import crew_places,VEHICLES,equipment_family,component_role
from bridge.gem import formation_positions,saved_variable
from bridge.core import BridgeError

class FormationTests(unittest.TestCase):
    def test_operating_seats_include_local_extensions_and_ignore_comments(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/'entities.pak'
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('-vehicle/btr/scout/scout.def','{extension "crew.ext"}')
                z.writestr('-vehicle/btr/scout/crew.ext','("crew_human" place(gunner))\n;("crew_human" place(commander))\n{placer {place "driver" {visor "main"}}}')
                z.writestr('-vehicle/tank_light/tank/tank.def','("crew_4_human")')
                z.writestr('-vehicle/cannon/gun/gun.def','("crew_wheeled_gun")')
                z.writestr('-vehicle/car/truck/truck.def','("crew_2_human")')
            entries={key:(str(archive),name) for key,name in [('scout','-vehicle/btr/scout/scout.def'),('tank','-vehicle/tank_light/tank/tank.def'),('gun','-vehicle/cannon/gun/gun.def'),('truck','-vehicle/car/truck/truck.def')]}
            self.assertEqual(crew_places('scout',entries),['gunner','driver'])
            self.assertEqual(set(crew_places('tank',entries)),{'driver','gunner','charger','commander'})
            self.assertEqual(len(crew_places('gun',entries)),6)
            self.assertEqual(crew_places('truck',entries),['driver','commander'])

    def test_formations_at_both_edges_stay_inside_and_crew_share_position(self):
        roster=[]
        for player in (0,1):
            for _ in range(45): roster.append({'player':player,'mid':len(roster)+1})
        roster.append({'player':0,'mid':91,'parent_mid':1})
        positions=formation_positions(roster,[[990,0],[-990,0]],[-1000,-1000,1000,1000])
        for x,y in positions.values():
            self.assertTrue(-850<=x<=850)
            self.assertTrue(-850<=y<=850)
        self.assertEqual(positions[91],positions[1])
        self.assertEqual(len(set(positions[a['mid']] for a in roster if not a.get('parent_mid'))),90)

    def test_light_tank_is_native_machine_gun_panzer(self):
        self.assertEqual(VEHICLES['ger']['light_tank'],'pz1b')
    def test_specialized_tank_equipment_is_not_folded_into_normal_tanks(self):
        self.assertEqual(equipment_family('light_tank_aa_chassis_1'),'light_tank_aa_chassis')
        self.assertEqual(equipment_family('medium_tank_destroyer_chassis_2'),'medium_tank_destroyer_chassis')
        self.assertEqual(equipment_family('light_tank_artillery_equipment_1'),'light_tank_artillery_equipment')
        self.assertEqual(component_role({'type':'light_sp_anti_air_brigade'}),'sp_anti_air')
    def test_native_saved_variables_are_read_from_helpers_not_trigger_actions(self):
        text='{mission {Helpers {vars {"hmb_finished" {value 0}} {"hmb_winner" {value 0}}} {triggers {"end" {actions {"set_i" {var hmb_finished} {value 1}}}}}}}'
        self.assertEqual(saved_variable(text,'hmb_finished'),0)
        self.assertEqual(saved_variable(text,'hmb_winner'),0)
        with self.assertRaises(BridgeError): saved_variable(text.replace('{"hmb_finished" {value 0}}','{"hmb_finished" {value 0}} {"hmb_finished" {value 1}}'),'hmb_finished')

if __name__=='__main__': unittest.main()
