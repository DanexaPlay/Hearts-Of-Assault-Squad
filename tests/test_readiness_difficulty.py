import copy,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from bridge.core import BridgeError
from bridge.readiness import organization_ratio,deployed_count
from bridge.difficulty import install_profiles,MAPPING
from bridge.equipment import allocate_models
from bridge.formations import build_roster
from bridge.native import NativeHOI
from bridge.hoi import read_campaign
from bridge.transition import AutomaticTransfer


class ReadinessDifficultyTests(unittest.TestCase):
    def test_campaign_reader_preserves_saved_difficulty(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'difficulty.hoi4'
            for difficulty in MAPPING:
                path.write_text('HOI4txt\ndifficulty="'+difficulty+'"\ncountries={}\n',encoding='utf8')
                self.assertEqual(read_campaign(path)['difficulty'],difficulty)

    def test_organization_uses_division_maximum_and_rejects_stale_values(self):
        d={'id':'1:51','organization_points':30}
        b={'organization_scaling_required':True,'organization_snapshot':{'1:51':{'current':30,'maximum':60}}}
        self.assertEqual(organization_ratio(b,d),.5)
        self.assertEqual(deployed_count(10,.5),5)
        self.assertEqual(deployed_count(10,0),1)
        self.assertEqual(deployed_count(0,0),0)
        for record in ({'current':30,'maximum':0},{'current':31,'maximum':60},{'current':float('nan'),'maximum':60}):
            with self.assertRaises(BridgeError):organization_ratio({**b,'organization_snapshot':{'1:51':record}},d)
        with self.assertRaises(BridgeError):organization_ratio({'organization_scaling_required':True},d)

    def test_model_minority_does_not_override_low_organization_actor_budget(self):
        items=[{'variant_id':str(i),'represented_amount':1} for i in range(5)]
        self.assertEqual(len(allocate_models(items,1,preserve_variants=False)),1)
        self.assertEqual(len(allocate_models(items,1)),5)

    def test_full_roster_keeps_crews_and_strategic_weights_when_scaled(self):
        definitions={'infantry':{'manpower':1000,'need':{'infantry_equipment':100}},
                     'light_armor':{'manpower':1000,'need':{'light_tank_chassis':100}}}
        gear=[{'variant_id':'1:70','amount':100,'variant':{'model':'infantry_equipment_1'}},
              {'variant_id':'2:70','amount':100,'variant':{'model':'light_tank_chassis_1'}}]
        d={'id':'1:51','organization_points':30,'manpower':2000,'equipment':gear,'template':{'name':'test','components':[
            {'type':'infantry','group':'regiments'},{'type':'light_armor','group':'regiments'}]}}
        b={'attacker':{'country':'GER','ideology':'fascism','divisions':[d]},
           'defender':{'country':'GER','ideology':'fascism','divisions':[copy.deepcopy(d)]},
           'organization_snapshot':{'1:51':{'current':30,'maximum':60}}}
        cfg={'hoi4':'unused','mow':'unused','soldiers_per_actor':100,'equipment_per_vehicle':25,'max_vehicles_per_component':4,
             'country_overrides':{},'native_countries':{'GER':'ger'}}
        breeds={'mp/ger/'+s for s in ('rifle','mgun','smg','tankman')}
        with patch('bridge.formations.unit_definitions',return_value=definitions),patch('bridge.formations.catalog',return_value=({'pz1b':None},breeds)),patch('bridge.formations.crew_places',return_value=['gunner','driver']):
            for current,expected_infantry,expected_tanks in [(30,5,2),(0,1,1),(60,10,4)]:
                for side in ('attacker','defender'):b[side]['divisions'][0]['organization_points']=current
                b['organization_snapshot']['1:51']['current']=current
                roster,report=build_roster(b,cfg)
                for side in ('attacker','defender'):
                    own=[a for a in roster if a['side']==side]
                    self.assertEqual(sum(a['kind']=='infantry' for a in own),expected_infantry)
                    self.assertEqual(sum(a['kind']=='vehicle' for a in own),expected_tanks)
                    self.assertEqual(sum(a['kind']=='crew' for a in own),expected_tanks*2)
                    self.assertAlmostEqual(sum(a['represented_manpower'] for a in own),2000)
                    self.assertAlmostEqual(sum(e['amount'] for a in own for e in a['represented_equipment']),200)
                    mids={a['mid'] for a in own if a['kind']=='vehicle'}
                    self.assertTrue(all(a['parent_mid'] in mids for a in own if a['kind']=='crew'))

    def test_all_difficulties_use_shipped_profiles_even_if_menu_retains_another_level(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);pak=root/'logic.zip'
            with zipfile.ZipFile(pak,'w') as z:
                for name in set(MAPPING.values()):z.writestr('set/difficulty/'+name+'.dl',name)
                z.writestr('set/difficulty/difficulty_generic.inc','generic')
            with zipfile.ZipFile(pak) as z:
                for source,target in MAPPING.items():
                    dest=root/source;report=install_profiles({'difficulty':source},dest,z)
                    self.assertEqual(report['mow'],target)
                    for level in ('easy','normal','hard','heroic'):
                        self.assertEqual((dest/'resource/set/difficulty'/(level+'.dl')).read_text(),target)
                with self.assertRaises(BridgeError):install_profiles({'difficulty':'unknown'},root/'invalid',z)

    def test_native_organization_requires_same_campaign_hour_and_saved_current_value(self):
        client=NativeHOI();health={'paused':True,'game_hour':100,'date':'1936.1.1.12'}
        b={'campaign_id':'campaign','snapshot_date':health['date'],
           'attacker':{'divisions':[{'id':'1:51','organization_points':30}]},'defender':{'divisions':[]}}
        good={'campaign_id':'campaign','hour':100,'units':{'1:51':{'current':30,'maximum':60}}}
        for result,valid in [(good,True),({**good,'hour':101},False),({**good,'campaign_id':'other'},False),
                             ({**good,'units':{'1:51':{'current':29,'maximum':60}}},False)]:
            with patch.object(client,'health',return_value=health),patch.object(client,'request',side_effect=[{'ok':True},{'ok':True,'result':json.dumps(result)}]) as request:
                if valid:self.assertEqual(client.organization_snapshot(b,100),good)
                else:
                    with self.assertRaises(BridgeError):client.organization_snapshot(b,100)
                self.assertTrue(all(call.args[0]=='/lua' for call in request.call_args_list))

    def test_automatic_generation_receives_required_native_organization_or_stops(self):
        for failure in (False,True):
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'snapshot.hoi4';source.write_text('snapshot')
                auto=AutomaticTransfer({'hoi4_user':folder,'hoi4':'unused'},root/'sessions')
                auto.request('HMB_REQUEST: country=GER seq=1')
                auto.pending.update(native_capture_verified=True,native_health={'game_hour':100})
                d={'country':'GER','id':'1:51','organization_points':30}
                c={'speed':'0','mods':[],'countries':{'GER':{'hmb_request_seq':1}},'combats':[
                    {'combat_id':'3:62','province':10,'attacker':[d],'defender':[]}]}
                b={'id':'a'*32,'attacker':{'divisions':[d]},'defender':{'divisions':[]}}
                organization={'units':{'1:51':{'current':30,'maximum':60}}}
                with patch('bridge.transition.read_campaign',return_value=c),patch('bridge.transition.vanilla_metadata',return_value={'state':1,'terrain':'plains','source':'fixture'}),patch('bridge.transition.export_combat',return_value=b),patch('bridge.native.NativeHOI') as native,patch('bridge.transition.generate',return_value={}) as generate,patch('bridge.transition.Ledger'):
                    native.return_value.organization_snapshot.return_value=organization
                    if failure:native.return_value.organization_snapshot.side_effect=BridgeError('stale snapshot')
                    if failure:
                        with self.assertRaises(BridgeError):auto.prepare(source)
                        generate.assert_not_called()
                        self.assertEqual(auto.pending['status'],'failed')
                    else:
                        auto.prepare(source)
                        exported=generate.call_args.args[0]
                        self.assertTrue(exported['organization_scaling_required'])
                        self.assertEqual(exported['organization_snapshot'],organization['units'])
