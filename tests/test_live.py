import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bridge.core import BridgeError,digest
from bridge.live import build_plan,lua,apply_session


def fixture(winner='attacker'):
    b={'schema':1,'id':'a'*32,'province':20,'state':1,'war_confirmed':True,'paused_confirmed':True,
       'campaign_id':'campaign','combat_id':'3:62','attacker':{'country':'GER','divisions':[]},'defender':{'country':'SOV','divisions':[]}}
    state={'campaign_id':'campaign','hour':100,'flags':{},'units':{},'combats':{'3:62':{'province':20,'attacker':{'1:51':True},'defender':{'2:51':True}}},
           'provinces':{'10':{'controller':'GER'},'20':{'controller':'SOV'},'30':{'controller':'SOV'}},'occupants':{}}
    result={'battle_id':b['id'],'winner':winner,'evidence':{'kind':'mow_save'},'losses':{},'equipment_losses':{}}
    for i,(side,country,province) in enumerate([('attacker','GER',10),('defender','SOV',20)],1):
        key=f'{i}:51';d={'id':key,'country':country,'province':province,'manpower':1000,'required_manpower':1000,'organization_points':40,'strength_hp':100,
            'template':{'id':f'{i}:52','components':[{'type':'infantry'}]},'equipment':[{'variant_id':'8:70','amount':90},{'variant_id':'9:70','amount':10}]}
        b[side]['divisions'].append(d)
        state['units'][key]={'country':country,'owner':country,'logical_country':country,'province':province,'template_id':i,'manpower':1000,'hp':10000000,'org':4000000,'combat_count':1,
            'manpower_values':{'0':{'addr':100,'amount':333,'tag':i},'1':{'addr':108,'amount':667,'tag':i}},
            'equipment':{'8:70':{'addr':200,'amount':9000000},'9:70':{'addr':216,'amount':1000000}}}
        loser=side!=winner
        result['losses'][side]=[{'index':0,'loss_ratio':.25 if loser else 0,'manpower_lost':250 if loser else 0,'organization_loss_ratio':.9 if loser else .2}]
        result['equipment_losses'][side]=[{'index':0,'variant_id':'8:70','amount_lost':22.5}] if loser else []
    result['battle_sha256']=digest(json.dumps(b,sort_keys=True).encode())
    return b,result,state


class LivePlanTests(unittest.TestCase):
    def setUp(self):
        self.defs=patch('bridge.formations.unit_definitions',return_value={'infantry':{'max_strength':100}})
        self.defs.start();self.addCleanup(self.defs.stop)

    def test_attacker_victory_moves_loser_and_preserves_exact_mixed_gear(self):
        b,r,s=fixture();p=build_plan(b,r,s,{'2:51':30})
        self.assertEqual(p['targets']['1:51']['province'],20)
        target=p['targets']['2:51'];self.assertEqual(target['province'],30)
        self.assertEqual(target['manpower'],750)
        self.assertEqual([v['value'] for v in target['manpower_values'].values()],[250,500])
        self.assertEqual(target['org'],400000)
        self.assertEqual(target['equipment']['8:70']['value'],6750000)
        self.assertEqual(target['equipment']['9:70']['value'],1000000)

    def test_defender_victory_cancels_attack_at_origin_without_territory_change(self):
        b,r,s=fixture('defender');p=build_plan(b,r,s)
        self.assertEqual(p['targets']['1:51']['province'],10)
        self.assertEqual(p['targets']['1:51']['manpower'],750)
        self.assertEqual(p['targets']['2:51']['province'],20)

    def test_missing_enemy_or_unsafe_retreat_rejected(self):
        for edit in ('missing','hostile','occupied'):
            b,r,s=fixture()
            if edit=='missing':s['units'].pop('2:51')
            if edit=='hostile':s['provinces']['30']['controller']='GER'
            if edit=='occupied':s['occupants']['99:51']={'province':30,'country':'GER'}
            with self.assertRaises(BridgeError):build_plan(b,r,s,{'2:51':30})

    def test_changed_equipment_manpower_campaign_org_or_participants_rejected(self):
        for change in ('gear','manpower','campaign','org','combat','owner','template'):
            b,r,s=fixture()
            if change=='gear':s['units']['1:51']['equipment']['8:70']['amount']-=1
            if change=='manpower':s['units']['1:51']['manpower']-=1
            if change=='campaign':s['campaign_id']='other'
            if change=='org':s['units']['1:51']['org']-=100
            if change=='combat':s['combats']['3:62']['attacker']['99:51']=True
            if change=='owner':s['units']['1:51']['owner']='USA'
            if change=='template':s['units']['1:51']['template_id']=99
            with self.subTest(change=change),self.assertRaises(BridgeError):build_plan(b,r,s,{'2:51':30})

    def test_duplicate_result_pending_result_and_other_combat_rejected(self):
        for flag in ('hmb_','hmb_pending_'):
            b,r,s=fixture();s['flags'][flag+b['id']]=1
            with self.assertRaises(BridgeError):build_plan(b,r,s,{'2:51':30})
        b,r,s=fixture();s['combats']['4:62']=copy.deepcopy(s['combats']['3:62'])
        with self.assertRaises(BridgeError):build_plan(b,r,s,{'2:51':30})

    def test_more_than_25_percent_is_rejected_even_if_consistent(self):
        b,r,s=fixture();r['losses']['defender'][0].update(manpower_lost=500,loss_ratio=.5)
        with self.assertRaises(BridgeError):build_plan(b,r,s,{'2:51':30})


    def test_lua_serialization_escapes_strings_and_refuses_nonfinite_values(self):
        self.assertEqual(lua({'id':'1:51','enabled':True}),'{["id"]="1:51",["enabled"]=true}')
        self.assertEqual(lua('"\n'),'"\\\"\\n"')
        for value in (math.nan,math.inf,object()):
            with self.assertRaises(BridgeError):lua(value)

    def test_recorded_return_never_reaches_native_mutations_again(self):
        b,r,s=fixture()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name,data in [('battle.json',b),('result.json',r),('live-return.json',{'stage':'applying'})]:
                (root/name).write_text(json.dumps(data))
            with patch('bridge.live.LiveHOI') as api:
                with self.assertRaises(BridgeError):apply_session(root)
                api.assert_not_called()

    def test_direct_dispatch_never_uses_save_import_or_retries_failure(self):
        from unittest.mock import Mock
        from bridge.transition import complete_native_return
        transfer=Mock();transfer.pending={'path':'example'}
        with patch('bridge.live.apply_session',return_value={'stage':'verified'}) as direct,patch('bridge.native_return.prepare') as save:
            result=complete_native_return(transfer,{'native_return_mode':'direct'})
            self.assertFalse(result['save_or_load_used']);direct.assert_called_once_with('example');save.assert_not_called()
        transfer.pending={'path':'example'}
        with patch('bridge.live.apply_session',side_effect=BridgeError('partial failure')) as direct,patch('bridge.native_return.prepare') as save:
            with self.assertRaises(BridgeError):complete_native_return(transfer,{'native_return_mode':'direct'})
            direct.assert_called_once();save.assert_not_called()
            self.assertNotIn('strategic_result_applied',transfer.pending)
            with self.assertRaises(BridgeError):complete_native_return(transfer,{'native_return_mode':'direct'})
            direct.assert_called_once()

    def test_completed_or_interrupted_return_is_never_dispatched_again(self):
        from unittest.mock import Mock
        from bridge.transition import complete_native_return
        for state in [{'strategic_result_applied':True}]+[{'native_return_stage':s} for s in ['applying_direct','preparing','loading','verified']]:
            transfer=Mock();transfer.pending={'path':'example',**state}
            with patch('bridge.live.apply_session') as direct,patch('bridge.native_return.prepare') as save:
                with self.assertRaises(BridgeError):complete_native_return(transfer,{'native_return_mode':'direct'})
                direct.assert_not_called();save.assert_not_called()

    def test_synthetic_result_needs_explicit_fixture_mode(self):
        b,r,s=fixture();r['evidence']['kind']='test_fixture'
        with self.assertRaises(BridgeError):build_plan(b,r,s,{'2:51':30})
        self.assertEqual(build_plan(b,r,s,{'2:51':30},test_fixture=True)['targets']['2:51']['manpower'],750)
