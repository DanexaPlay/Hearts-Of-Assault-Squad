import unittest,tempfile
from pathlib import Path
from bridge.gem import analyze_saved_actors,vehicle_destroyed,terminal_autosave_winner
from bridge.core import BridgeError

class NativeCasualtyTests(unittest.TestCase):
    def setUp(self):
        self.roster=[{'mid':1,'kind':'vehicle','player':0},
            {'mid':2,'kind':'crew','player':0,'parent_mid':1},
            {'mid':3,'kind':'crew','player':0,'parent_mid':1},
            {'mid':4,'kind':'infantry','player':1},
            {'mid':5,'kind':'infantry','player':0}]
        self.scene='{mission {Entity "pz1b" 0x4 {MID 1} {Able "-repaired" "-select" "burning"} {Chassis {Broken}} {Component "body" {State broken}}} {Human "mp/rus/rifle" 0x9 {MID 4} {Extender "vitality" {Health {current 70.4734}}} {FsmState "squat"}} {Human "mp/ger/rifle" 0xa {MID 5} {Extender "vitality" {Dead} {Health {current 0}}} {FsmState "dead"}}}'
        self.statistics='{game {Statistics {processor_0 {player "0"} {man {lost 3}} {vehicle {lost 1}}} {processor_3 {player "1"}}}}'
    def test_destroyed_hull_removed_crew_and_wounded_survivor(self):
        audit=analyze_saved_actors(self.roster,self.scene,self.statistics)
        self.assertEqual(audit['dead_mids'],[1,2,3,5])
        self.assertEqual(audit['removed_crew_mids'],[2,3])
    def test_repairable_turret_is_not_destroyed_equipment(self):
        gun='{Entity "zis3" 0x511 {Operatable} {Component "turret" {State broken} {RepairTimeLeft 17223}}}'
        self.assertFalse(vehicle_destroyed(gun))
        self.assertFalse(vehicle_destroyed('{Entity "tank" 0x4 {Chassis {Broken}} {Component "engine" {State broken}}}'))
    def test_exploded_body_and_burned_truck_require_native_destruction_markers(self):
        wreck='{Entity "lefh18" 0x1 {SkeletonSrc "lefh18_xx"} {Interaction {Flags "no_burn_volumes" "broken"}} {Able "-repaired" "-select" "exploded"} {Component "body" {State destroyed}}}'
        self.assertTrue(vehicle_destroyed(wreck))
        self.assertFalse(vehicle_destroyed(wreck.replace('"body"','"turret"')))
        self.assertFalse(vehicle_destroyed(wreck.replace('{State destroyed}','{State destroyed} {RepairTimeLeft 123}')))
        truck='{Entity "zis5" 0x2 {Extender "burning" {State 1 6.612 0} {Burned}} {Interaction {Flags "burn_fire" "broken"}} {Operatable} {Able "burning"} {Component "fuel" {State broken}}}'
        self.assertTrue(vehicle_destroyed(truck))
        for changed in (truck.replace('{Burned}',''),truck.replace('"broken"','"smoke"'),truck.replace('{Able "burning"}','{Able}')):
            self.assertFalse(vehicle_destroyed(changed))
    def test_unburned_knocked_out_hull_and_repairable_variants(self):
        wreck='{Entity "pz1b" 0x4 {Interaction {Flags "broken"}} {Able "-select"} {Chassis {Broken}} {Component "body" {State broken}}}'
        self.assertTrue(vehicle_destroyed(wreck))
        for damaged in [wreck.replace('{State broken}','{State broken} {RepairTimeLeft 500}'),
                        wreck.replace('{Able "-select"}','{Able "-select"} {Operatable}'),
                        wreck.replace('Component "body"','Component "engine"'),
                        wreck.replace('{Chassis {Broken}}','{Chassis}'),
                        wreck.replace('{Flags "broken"}','{Flags "rotate_turret"}')]:
            self.assertFalse(vehicle_destroyed(damaged))
    def test_decorative_flag_cannot_be_read_as_tank_with_same_mid(self):
        roster=[dict(a) for a in self.roster];roster[0]['entity']='pz1b'
        scene=self.scene.replace('Entity "pz1b"','Entity "flag_point_1"')
        with self.assertRaises(BridgeError): analyze_saved_actors(roster,scene,self.statistics)
    def test_missing_crew_requires_exact_statistics(self):
        with self.assertRaises(BridgeError): analyze_saved_actors(self.roster,self.scene)
        with self.assertRaises(BridgeError): analyze_saved_actors(self.roster,self.scene,self.statistics.replace('{lost 3}','{lost 2}'))
    def test_missing_infantry_is_not_guessed_from_aggregate_statistics(self):
        with self.assertRaises(BridgeError): analyze_saved_actors(self.roster+[{'mid':6,'kind':'infantry','player':1}],self.scene,self.statistics)
    def test_terminal_culled_infantry_still_requires_exact_counts(self):
        roster=self.roster+[{'mid':6,'kind':'infantry','player':1}]
        statistics=self.statistics.replace('{processor_3 {player "1"}}','{processor_3 {player "1"} {man {lost 1}}}')
        audit=analyze_saved_actors(roster,self.scene,statistics,terminal_snapshot=True)
        self.assertEqual(audit['culled_human_mids'],[6])
        with self.assertRaises(BridgeError): analyze_saved_actors(roster,self.scene,self.statistics,terminal_snapshot=True)
    def test_score_and_timeout_endings_require_matching_completed_record(self):
        with tempfile.TemporaryDirectory() as folder:
            progress=Path(folder)/'game_progress.set'
            progress.write_text('{"single/hmb/battle:0" {completed} {outro "HMB fixture\\nПобеда"}}',encoding='utf8')
            for name in ('hmb_end_defender','hmb_score_win_attacker','hmb_time_win_attacker'):
                game='{game {Threads {trigger "'+name+'" {current "/3/"} {state "/3/" {delay 1}}}}}'
                self.assertEqual(terminal_autosave_winner({'id':'fixture'},game,progress)[0],'attacker')
                with self.assertRaises(BridgeError): terminal_autosave_winner({'id':'other'},game,progress)
            with self.assertRaises(BridgeError): terminal_autosave_winner({'id':'fixture'},game.replace('hmb_time_win_attacker','hmb_time_win_defender'),progress)
            progress.write_text('{"single/hmb/battle:0" {completed} {outro "HMB fixture\\nПоражение"}}',encoding='utf8')
            self.assertEqual(terminal_autosave_winner({'id':'fixture'},game.replace('hmb_time_win_attacker','hmb_time_win_defender'),progress)[0],'defender')

if __name__=='__main__': unittest.main()
