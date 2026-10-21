import re,tempfile,unittest
from pathlib import Path
from bridge.hoi import read_campaign,export_combat,line_positions
from bridge.core import BridgeError


def division(n,location):
    return ('\t\t\tdivision={\n\t\t\t\tid={ id='+str(n)+' type=51 }\n'
            '\t\t\t\tlocation='+str(location)+'\n'
            '\t\t\t\tstrength=100 organisation=40\n'
            '\t\t\t\tarmy_manpower={ army_manpower_value={ value={ value=1000 } } army_manpower_need={ value={ value=1000 } } }\n\t\t\t}\n')


class CampaignScopeTests(unittest.TestCase):
    def save(self,root):
        text=('HOI4txt\ndate="1936.1.1.12"\nspeed=0\nplayer="GER"\ngame_unique_id="c"\n'
              'countries={\n\tGER={ ruling_party=fascism\n\t\t\thmb_request_seq=7.000\n'+
              division(1,10)+division(3,10)+division(4,99)+'\t}\n\tSOV={ ruling_party=communism\n'+division(2,20)+'\t}\n}\n'
              '\tland_combat={ id={ id=8 type=62 } location=20 attacker={ unit={ id=1 type=51 } } defender={ unit={ id=2 type=51 } } }\n')
        path=root/'campaign.hoi4';path.write_text(text,encoding='utf8');return path

    def test_literal_prefixes_match_regex_including_bounds(self):
        text='key=1\notherkey=2\n\tkey=3\nkey=4\nkey=5'
        for start,end in ((0,len(text)),(1,len(text)),(0,30),(15,35)):
            expected=[m.start() for m in re.compile(r'^key=',re.M).finditer(text,start,end)]
            self.assertEqual(list(line_positions(text,'key=',start,end)),expected)

    def test_fast_reader_keeps_colocated_idle_divisions_and_export_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            path=self.save(Path(folder));full=read_campaign(path);fast=read_campaign(path,combat_units_only=True)
            self.assertEqual(set(fast['divisions']),{'1:51','2:51','3:51'})
            self.assertEqual(fast['countries']['GER']['hmb_request_seq'],7)
            self.assertEqual(fast['combats'],full['combats'])
            for key in fast['divisions']:self.assertEqual(fast['divisions'][key],full['divisions'][key])
            a=export_combat(full,'8:62',1,'plains');b=export_combat(fast,'8:62',1,'plains')
            a.pop('id');b.pop('id');self.assertEqual(a,b)
            self.assertFalse(b['all_divisions_in_locations_confirmed'])

    def test_unknown_participant_and_duplicate_identity_fail(self):
        for mode in ('unknown','duplicate'):
            with tempfile.TemporaryDirectory() as folder:
                path=self.save(Path(folder));text=path.read_text()
                text=text.replace('unit={ id=1 type=51 }','unit={ id=90 type=51 }') if mode=='unknown' else text.replace('id={ id=4 type=51 }','id={ id=1 type=51 }')
                path.write_text(text)
                with self.assertRaises(BridgeError):read_campaign(path,combat_units_only=True)
