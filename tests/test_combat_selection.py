import tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from bridge.native import NativeHOI
from bridge.core import BridgeError
from bridge.transition import select_requested_combat,request_fields


class CombatSelectionTests(unittest.TestCase):
    def test_native_identity_selects_only_the_clicked_battle_among_many(self):
        campaign={'player_country':'GER','countries':{'GER':{'hmb_request_seq':9}},'combats':[
            {'combat_id':'1:62','province':100,'attacker':[{'country':'GER'}],'defender':[{'country':'SOV'}]},
            {'combat_id':'2:62','province':200,'attacker':[{'country':'GER'}],'defender':[{'country':'SOV'}]}]}
        fields=request_fields('HMB_REQUEST: country=GER seq=9 selection=native_v1')
        with self.assertRaises(BridgeError):select_requested_combat(campaign,fields)
        fields.update(combat='2:62',province='200')
        self.assertEqual(select_requested_combat(campaign,fields)['combat_id'],'2:62')
        fields['province']='100'
        with self.assertRaises(BridgeError):select_requested_combat(campaign,fields)

    def test_captured_record_must_match_button_sequence_hour_and_country(self):
        import json
        native=NativeHOI();request={'country':'GER','seq':'9'};state={'game_hour':123}
        good={'combat':'2:62','province':200,'country':'GER','seq':9,'game_hour':123,'campaign_id':'fixture','source':'combat_button_effect_v1'}
        native.request=Mock(return_value={'result':json.dumps(good)})
        self.assertEqual(native.combat_selection(request,state),good)
        for bad in ({**good,'seq':8},{**good,'game_hour':122},{**good,'country':'SOV'},{**good,'combat':'2:61'},{'error':'No clicked combat'},{**good,'province':True}):
            native.request.return_value={'result':json.dumps(bad)}
            with self.assertRaises(BridgeError):native.combat_selection(request,state)

    def test_capture_binds_selection_before_named_snapshot(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);transfer=Mock();transfer.saves=root
            transfer.pending={'status':'waiting_snapshot','path':str(root/('a'*32)),'request':{'country':'GER','seq':'9','selection':'native_v1'}}
            native=NativeHOI();state={'paused':True,'game_hour':123}
            native.ensure_paused=Mock(return_value=state);native.health=Mock(return_value=state)
            selected={'combat':'2:62','province':200,'country':'GER','seq':9,'game_hour':123,'campaign_id':'fixture','source':'combat_button_effect_v1'}
            native.request=Mock(side_effect=[{'result':json.dumps(selected)},{'ok':True}])
            native.capture(transfer)
            self.assertEqual(transfer.pending['request']['combat'],'2:62')
            self.assertEqual(transfer.pending['selected_combat'],selected)
            self.assertEqual(native.request.call_args_list[0].args[0],'/lua')
            self.assertEqual(native.request.call_args_list[1].args[0],'/console')

    def test_missing_button_capture_never_creates_a_snapshot(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            transfer=Mock();transfer.saves=Path(folder)
            transfer.pending={'status':'waiting_snapshot','path':str(Path(folder)/('a'*32)),'request':{'country':'GER','seq':'9','selection':'native_v1'}}
            native=NativeHOI();native.ensure_paused=Mock(return_value={'paused':True,'game_hour':123})
            native.request=Mock(return_value={'result':json.dumps({'error':'No captured selection'})})
            with self.assertRaises(BridgeError):native.capture(transfer)
            self.assertEqual(native.request.call_count,1)
            self.assertEqual(native.request.call_args.args[0],'/lua')
            self.assertNotIn('native_save_name',transfer.pending)
