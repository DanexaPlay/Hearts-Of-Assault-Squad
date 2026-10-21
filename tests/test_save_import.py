import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from bridge.core import BridgeError,make_roster,calculate_result,validate_result,Ledger
from bridge.hoi import read_campaign,export_combat
from bridge.save_import import prepare_save,verify_loaded_save

def division(i,province,orders=True):
    return ('\t\t\tdivision={ id={ id='+str(i)+' type=51 } id={ id='+str(i)+' type=51 } location='+str(province)+
        ' strength=100 organisation=40 '+('path={ 20 } movement_progress=0.5 ' if orders else '')+
        'equipment={ equipment={ id={ id=8 type=70 } amount=90 } } '
        'army_manpower={ army_manpower_value={ value={ value=333 } value={ value=667 } } army_manpower_need={ value={ value=1000 } } } }\n')

class SaveImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.source=self.root/'original.hoi4'
        self.text=('HOI4txt\ndate="1936.1.1.12"\nspeed=0\ngame_unique_id="test"\nflags={ }\nstates={ }\nprovinces={ }\ncountries={\n\tGER={ ruling_party=fascism\n'+
            division(1,10)+division(4,10,False)+'\t}\n\tSOV={ ruling_party=communism\n'+division(2,20)+'\t}\n}\n'+
            '\tland_combat={ id={ id=3 type=62 } location=20 attacker={ unit={ id=1 type=51 } } defender={ unit={ id=2 type=51 } } }\n')
        self.source.write_text(self.text,encoding='utf8')
        self.b=export_combat(read_campaign(self.source),'3:62',1,'plains')
        self.controls=patch('bridge.geography.controllers',return_value={10:'GER',20:'SOV',30:'SOV'})
        self.controls.start(); self.addCleanup(self.controls.stop)
        self.neighbors=patch('bridge.geography.neighbors',return_value={10,30})
        self.neighbors.start(); self.addCleanup(self.neighbors.stop)
    def result(self,winner):
        roster=make_roster(self.b)
        return calculate_result(self.b,roster,winner,[a['mid'] for a in roster if a['side']!=winner],{'kind':'mow_save'})
    def test_defeat_preserves_original_unselected_unit_and_cancels_attack(self):
        output=self.root/'prepared.hoi4'; report=prepare_save(self.b,self.result('defender'),self.source,output)
        self.assertEqual(self.source.read_text(encoding='utf8'),self.text)
        edited=output.read_text(encoding='utf8'); self.assertIn(division(4,10,False),edited)
        campaign=read_campaign(output); self.assertEqual(len(campaign['divisions']),3)
        self.assertEqual(campaign['divisions']['1:51']['manpower'],750)
        self.assertEqual(campaign['divisions']['1:51']['organization_points'],4)
        self.assertEqual(campaign['divisions']['1:51']['province'],10)
        self.assertNotIn('movement_progress',edited.split('division={')[1])
        self.assertEqual(campaign['combats'],[])
        self.assertEqual(report['changes'][0]['retreat'],'attack_cancelled_at_origin')
        with self.assertRaises(BridgeError): prepare_save(self.b,self.result('defender'),self.source,output)
        with self.assertRaises(BridgeError): verify_loaded_save(report,output)
    def test_defending_retreat_and_control_transfer(self):
        output=self.root/'win.hoi4'
        report=prepare_save(self.b,self.result('attacker'),self.source,output,{'2:51':30})
        campaign=read_campaign(output)
        self.assertEqual(campaign['divisions']['2:51']['province'],30)
        self.assertEqual(campaign['divisions']['2:51']['manpower'],750)
        self.assertIn('20={ controller="GER" }',output.read_text(encoding='utf8'))
        self.assertEqual(report['changes'][1]['retreat'],'moved_to_friendly_neighbor')
    def test_invalid_retreat_produces_no_output(self):
        for destination in (10,99,None):
            output=self.root/'bad.hoi4'
            with self.assertRaises(BridgeError): prepare_save(self.b,self.result('attacker'),self.source,output,{'2:51':destination})
            self.assertFalse(output.exists())
    def test_rejects_duplicate_losses_and_excess_equipment(self):
        r=self.result('defender'); r['losses']['attacker'].append(copy.deepcopy(r['losses']['attacker'][0]))
        with self.assertRaises(BridgeError): validate_result(self.b,r)
        r=self.result('defender'); r['equipment_losses']['attacker']=[{'index':0,'variant_id':'8:70','amount_lost':91}]
        with self.assertRaises(BridgeError): validate_result(self.b,r)
    def test_save_ledger_requires_fresh_snapshot_and_blocks_replay(self):
        ledger=Ledger(self.root/'ledger.sqlite'); self.addCleanup(ledger.db.close); ledger.register(self.b)
        output=self.root/'prepared.hoi4'
        report=ledger.prepare_save(self.b,self.result('defender'),self.source,output)
        with self.assertRaises(BridgeError): ledger.acknowledge_save(self.b['id'],output)
        # Synthetic round-trip tests verification only, not actual engine provenance.
        fresh=self.root/'synthetic-roundtrip.hoi4'; fresh.write_bytes(output.read_bytes()+b'\n# synthetic roundtrip\n')
        verified=ledger.acknowledge_save(self.b['id'],fresh)
        self.assertIn('matches prepared outcome',verified['stage'])
        self.assertEqual(ledger.db.execute('SELECT status FROM battles').fetchone()[0],'applied')
        with self.assertRaises(BridgeError): ledger.prepare_save(self.b,self.result('defender'),self.source,self.root/'replay.hoi4')

    def test_load_strength_normalization_requires_exact_template_calculation(self):
        output=self.root/'prepared.hoi4'
        report=prepare_save(self.b,self.result('defender'),self.source,output)
        expected=report['expected_divisions']['1:51']
        expected['template']={'components':[{'type':'infantry'}]}
        fresh=self.root/'synthetic-roundtrip.hoi4'
        text=output.read_text(encoding='utf8')
        with patch('bridge.formations.unit_definitions',return_value={'infantry':{'max_strength':120}}):
            fresh.write_text(text.replace('strength=75.00000','strength=90.00000'),encoding='utf8')
            verified=verify_loaded_save(report,fresh)
            self.assertEqual(verified['strength_recalculated_by_engine']['1:51']['expected_from_template_and_manpower'],90)
            fresh.write_text(text.replace('strength=75.00000','strength=90.10000'),encoding='utf8')
            with self.assertRaises(BridgeError): verify_loaded_save(report,fresh)

if __name__=='__main__': unittest.main()
