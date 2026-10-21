import unittest
from bridge.scoreboard import build_scoreboard
from bridge.objectives import build_objectives
from bridge.gem import blocks

class ScoreboardTests(unittest.TestCase):
    def setUp(self):
        self.b={'id':'fixture','attacker':{'country':'GER'},'defender':{'country':'SOV'}}
    def test_labels_cover_both_scores_and_player_side(self):
        hud=build_scoreboard(self.b,100)
        self.assertEqual(len(hud['labels']),202)
        self.assertEqual(hud['labels']['hmb_score_attacker_37'],'Ваши очки (GER): 37 / 100')
        self.b['player_side']='defender'
        hud=build_scoreboard(self.b,100)
        self.assertEqual(hud['labels']['hmb_score_defender_0'],'Ваши очки (SOV): 0 / 100')
        self.assertEqual(hud['labels']['hmb_score_attacker_100'],'Очки противника (GER): 100 / 100')
    def test_skipped_score_values_hide_cached_label_and_show_current_label(self):
        hud=build_scoreboard(self.b,100);text=hud['trigger']
        # A three-point tick can jump 37 -> 40: hide the actual cached label,
        # not score-1, and cache the new numeric value after displaying it.
        self.assertIn('{var "hmb_hud_attacker$"} {op "=="} {value 37}',text)
        self.assertIn('{name "hmb_score_attacker_37"} {state "hide"}',text)
        self.assertIn('{name "hmb_score_attacker_40"}} {"set_i" {var "hmb_hud_attacker$"} {op "="} {value 40}',text)
        list(blocks(text))
    def test_ai_recaptures_correct_side_and_enables_native_movement(self):
        self.b['player_side']='defender'
        objectives=build_objectives(self.b,{},[[0,0],[100,200]])
        ai=next(t for t in objectives['triggers'] if t.startswith('{"hmb_ai_orders"'))
        prepare=next(t for t in objectives['triggers'] if t.startswith('{"hmb_prepare"'))
        self.assertIn('{ai_move {mode "enable"}}',prepare)
        self.assertIn('{movement {speed "assault"}}',prepare)
        self.assertIn('{var "hmb_point_1_owner$"} {op "=="} {value 2}',ai)
        self.assertIn('{var "hmb_point_1_owner$"} {op "=="} {value 0}',ai)
        self.assertIn('{"delay" {time 15}}',ai)

if __name__=='__main__':unittest.main()
