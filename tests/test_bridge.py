import copy,json,tempfile,unittest,zipfile
from pathlib import Path
from bridge.core import *
from bridge.clausewitz import parse,read_save
from bridge.gem import blocks,parse_result,generate,parse_progress_result
from bridge.hoi import read_campaign,export_combat,verify_snapshot

class BridgeTests(unittest.TestCase):
    def setUp(self): self.b=read_json(ROOT/'examples/battle.example.json')
    def test_native_and_ideology(self):
        self.assertEqual(resolve_country('GER','democratic'),'ger')
        self.assertEqual(resolve_country('MON','communism'),'rus')
        self.assertIn(resolve_country('FRA','democratic'),['usa','eng'])
        self.assertEqual(resolve_country('FRA','democratic'),resolve_country('FRA','democratic'))
        with self.assertRaises(BridgeError): resolve_country('XYZ','unknown')
    def test_existing_map_and_approximation(self):
        self.assertEqual(choose_map('plains')[0],'multi/1v1_road')
        self.assertEqual(choose_map('urban',True)[0],'multi/1v1_frozen_river')
        self.assertIsNotNone(choose_map('mountain')[1])
        with self.assertRaises(BridgeError): choose_map('moon')
    def test_scaling_conserves_manpower(self):
        r=make_roster(self.b)
        for side in ('attacker','defender'):
            self.assertAlmostEqual(sum(a['represented_manpower'] for a in r if a['side']==side),2000)
        result=calculate_result(self.b,r,'attacker',[r[0]['mid']],{'kind':'test_fixture'})
        self.assertEqual(result['losses']['attacker'][0]['manpower_lost'],50)
    def test_damage_requires_verified_evidence_and_locations(self):
        r=make_roster(self.b)
        result=calculate_result(self.b,r,'attacker',[],{'kind':'manual'})
        with self.assertRaises(BridgeError): result_commands(self.b,result)
        result['evidence']['kind']='mow_save'
        with self.assertRaises(BridgeError): result_commands(self.b,result)
    def test_small_division_does_not_disappear_at_cap(self):
        self.b['attacker']['divisions'][0]['manpower']=100000
        self.b['attacker']['divisions'].append({'id':'small','province':9578,'manpower':1})
        roster=make_roster(self.b)
        self.assertEqual(len([a for a in roster if a['side']=='attacker']),60)
        self.assertAlmostEqual(sum(a['represented_manpower'] for a in roster if a['side']=='attacker'),100001)
        self.assertTrue(any(a['division_index']==1 for a in roster if a['side']=='attacker'))
    def test_replay_and_mismatched_result(self):
        self.b['all_divisions_in_locations_confirmed']=True
        r=make_roster(self.b); result=calculate_result(self.b,r,'attacker',[1],{'kind':'mow_save'})
        with tempfile.TemporaryDirectory() as d:
            ledger=Ledger(Path(d)/'ledger.sqlite'); ledger.register(self.b)
            cmd=ledger.stage(self.b,result)
            self.assertIn('NOT = { has_global_flag = hmb_',cmd)
            self.assertIn('set_province_controller =',cmd)
            self.assertIn('has_war_with = SOV',cmd)
            with self.assertRaises(BridgeError): ledger.stage(self.b,result)
            log=Path(d)/'game.log'; log.write_text('no success')
            with self.assertRaises(BridgeError): ledger.acknowledge(self.b['id'],log)
            log.write_text('HMB_APPLIED_'+self.b['id']); ledger.acknowledge(self.b['id'],log)
            ledger.db.close()
        result['battle_id']='0'*32
        with self.assertRaises(BridgeError): result_commands(self.b,result)
    def test_injection_and_invalid_numbers(self):
        for value in ['GER } log = hacked','GER\n','GER;']:
            with self.assertRaises(BridgeError): resolve_country(value,'fascism')
        self.b['province']=True
        with self.assertRaises(BridgeError): validate_battle(self.b)
        with self.assertRaises(BridgeError): fraction(float('nan'),'ratio')
    def test_clausewitz_duplicate_keys_quotes_and_spans(self):
        s='countries={GER={name="A } # B" division={id=1} division={id=2}}} # comment\n'
        tree=parse(s); country=tree.one('countries').one('GER')
        self.assertEqual(country.get('name'),'A } # B')
        self.assertEqual(len(country.all('division')),2)
        self.assertEqual(s[country.start:country.end],'GER={name="A } # B" division={id=1} division={id=2}}')
        with self.assertRaises(ValueError): parse('a={')
    def test_reject_binary(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'save.hoi4'; p.write_bytes(b'HOI4bin123')
            with self.assertRaises(ValueError): read_save(p)
    def test_gem_save_fixture_only(self):
        r=make_roster(self.b)
        text='{mission {Tags "hmb_'+self.b['id']+'" 0xf0001} {Helpers {vars {"hmb_finished" {value 1}} {"hmb_winner" {value 1}}}}'
        text+=''.join('{Human "'+a['breed']+'" '+hex(0xf0000+a['mid'])+' {MID '+str(a['mid'])+'} '+('{Dead}' if a['mid']==1 else '')+'}' for a in r)+'}'
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'0.mi'; p.write_text(text,encoding='utf8')
            result=parse_result(self.b,r,p)
            self.assertEqual(result['winner'],'attacker'); self.assertEqual(result['dead_mids'],[1])
            p.write_text(text.replace('{"hmb_finished" {value 1}}','{"hmb_finished" {value 0}}'),encoding='utf8')
            with self.assertRaises(BridgeError): parse_result(self.b,r,p)
    def test_installed_map_generation(self):
        if not (Path(config()['mow'])/'resource/map.pak').exists(): self.skipTest('Game not installed')
        with tempfile.TemporaryDirectory() as d:
            report=generate(self.b,config(),d)
            base=Path(d)/'mow_mod/resource/map'/self.b['mission_path']
            self.assertTrue((base/'0.mi').exists()); self.assertTrue((base/'map.ply').exists())
            with zipfile.ZipFile(Path(config()['mow'])/'resource/map.pak') as z:
                self.assertEqual((base/'map').read_bytes(),z.read('map/multi/1v1_road/map'))
            self.assertEqual(len(list(blocks((base/'0.mi').read_text()))),1)
            mission=(base/'0.mi').read_text(encoding='utf8')
            self.assertGreater(mission.index('{Entity "flag_point_1"'),mission.rindex('{Human "'))
    def test_observed_engine_progress_and_wrong_battle(self):
        r=make_roster(self.b)
        text='{game_progress {missions {"single/hmb/battle:0" {outro "HMB '+self.b['id']+'\\n\\nmission/outro_failed"} {stat "Врагов уничтожено :<x(135)> 4 Живой силы, 0 Техники\\nПотери союзников :<x(135)>10 Живой силы, 0 Техники"} {time 1791920555}}}}'
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'game_progress.set'; p.write_text(text,encoding='utf8')
            result=parse_progress_result(self.b,r,p)
            self.assertEqual(result['winner'],'defender')
            self.assertEqual(result['casualties'],{'attacker':10,'defender':4})
            self.assertEqual(result['losses']['defender'][0]['manpower_lost'],200)
            p.write_text(text.replace(self.b['id'],'0'*32),encoding='utf8')
            with self.assertRaises(BridgeError): parse_progress_result(self.b,r,p)

    def test_defeat_survives_total_tactical_losses(self):
        roster=make_roster(self.b)
        result=calculate_result(self.b,roster,'defender',[a['mid'] for a in roster if a['side']=='attacker'],{'kind':'test_fixture'})
        loss=result['losses']['attacker'][0]
        self.assertEqual(loss['manpower_lost'],500)
        self.assertEqual(loss['organization_loss_ratio'],0.9)
        self.assertTrue(loss['retreat_required'])
        self.assertEqual(loss['tactical_manpower_lost'],2000)

    def test_small_division_loss_never_exceeds_quarter(self):
        self.b['attacker']['divisions'][0]['manpower']=3
        roster=make_roster(self.b)
        result=calculate_result(self.b,roster,'defender',[a['mid'] for a in roster if a['side']=='attacker'],{'kind':'mow_save'})
        self.assertLessEqual(result['losses']['attacker'][0]['manpower_lost'],3*0.25)

    def test_defender_controls_his_own_force_and_progress_outcome(self):
        self.b['player_side']='defender'; roster=make_roster(self.b)
        self.assertTrue(all(a['player']==0 for a in roster if a['side']=='defender'))
        text='{game_progress {missions {"single/hmb/battle:0" {outro "HMB '+self.b['id']+'\\n\\nmission/outro_failed"} {stat "Врагов уничтожено :<x(135)> 4 Живой силы, 0 Техники\\nПотери союзников :<x(135)>10 Живой силы, 0 Техники"}}}}'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'game_progress.set'; path.write_text(text,encoding='utf8')
            result=parse_progress_result(self.b,roster,path)
            self.assertEqual(result['winner'],'attacker')
            self.assertEqual(result['casualties'],{'attacker':4,'defender':10})

    def test_text_save_combat_links_and_ambiguous_location(self):
        def division(i,province):
            return ('\t\t\tdivision={ id={ id='+str(i)+' type=51 } id={ id='+str(i)+' type=51 } location='+str(province)+
                    ' strength=100 organisation=40 army_manpower={ army_manpower_value={ value={ value=1000 } } army_manpower_need={ value={ value=1200 } } } }\n')
        text=('HOI4txt\ndate="1936.1.1.12"\nspeed=0\ngame_unique_id="test"\ncountries={\n\tGER={ ruling_party=fascism\n'+
              division(1,10)+'\t}\n\tSOV={ ruling_party=communism\n'+division(2,20)+'\t}\n}\n'+
              '\tland_combat={ id={ id=3 type=62 } location=20 attacker={ unit={ id=1 type=51 } } defender={ unit={ id=2 type=51 } } }\n')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'save.hoi4'; p.write_text(text,encoding='utf8')
            c=read_campaign(p); b=export_combat(c,'3:62',1,'plains')
            self.assertEqual(b['attacker']['divisions'][0]['manpower'],1000)
            self.assertTrue(b['all_divisions_in_locations_confirmed'])
            self.assertEqual(verify_snapshot(b,p)['campaign_id'],'test')
            p.write_text(text.replace('1936.1.1.12','1936.1.1.13'),encoding='utf8')
            with self.assertRaises(BridgeError): verify_snapshot(b,p)
            p.write_text(text.replace('value=1000','value=900'),encoding='utf8')
            with self.assertRaises(BridgeError): verify_snapshot(b,p)
            c['divisions']['4:51']={**c['divisions']['1:51'],'id':'4:51'}
            self.assertFalse(export_combat(c,'3:62',1,'plains')['all_divisions_in_locations_confirmed'])
            c['speed']='1'
            with self.assertRaises(BridgeError): export_combat(c,'3:62',1,'plains')

if __name__=='__main__': unittest.main()
