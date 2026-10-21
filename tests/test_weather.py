import tempfile,unittest
from pathlib import Path
from bridge.weather import read_weather,resolve_weather
from bridge.core import BridgeError,choose_map,config

SAMPLE='''weather={
 provinces={
  "142"={province=142 temperature=-11.15 water=0.001 snow=80 mud=0}
  "999"={province=999 temperature=12 snow=0}
 }
 regions={
  "12"={region=12 snow=yes temperature=-12.6}
 }
}
'''

class WeatherTests(unittest.TestCase):
    def test_saved_snow_and_region_are_read_only_for_requested_provinces(self):
        data=read_weather(SAMPLE,[142])
        self.assertEqual(set(data['provinces']),{'142'})
        self.assertEqual(data['provinces']['142']['snow_cover'],80)
        self.assertEqual(data['regions']['12']['conditions'],['snow'])
        self.assertEqual(read_weather('country={ weather={ } }',[142]),{'provinces':{},'regions':{}})

    def test_mud_presence_flags_in_other_combats_do_not_break_numeric_weather(self):
        # Actual second-transfer failure: province 142 had numeric snow;
        # unrelated active combats in 13237/13238 carried mud=yes.
        text=SAMPLE.replace('"999"={province=999 temperature=12 snow=0}',
            '"13237"={province=13237 temperature=16.85091 mud=yes water=200}\n'
            '  "13238"={province=13238 temperature=19.82532 mud=no water=200}')
        data=read_weather(text,[142,13237,13238])['provinces']
        self.assertEqual(data['142']['snow_cover'],80)
        self.assertIsNone(data['13237']['mud'])
        self.assertTrue(data['13237']['mud_present'])
        self.assertFalse(data['13238']['mud_present'])
        self.assertEqual(data['13237']['mud_raw'],'yes')
        self.assertEqual(data['13237']['mud_value_kind'],'flag')
        self.assertEqual(data['13237']['water'],200)
        self.assertEqual(read_weather(SAMPLE.replace('snow=80 mud=0','snow=80 mud=2.5'),[142])['provinces']['142']['mud'],2.5)

    def test_bad_weather_is_rejected(self):
        for text in (SAMPLE.replace('snow=80','snow=-1'),SAMPLE.replace('temperature=-11.15','temperature=nan')):
            with self.assertRaises(BridgeError):read_weather(text,[142])

    def test_region_membership_uses_whole_province_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);regions=root/'map/strategicregions';regions.mkdir(parents=True)
            (regions/'12.txt').write_text('strategic_region={ id=12 provinces={ 142 500 } }')
            (regions/'13.txt').write_text('strategic_region={ id=13 provinces={ 1142 } }')
            data=resolve_weather({'weather':read_weather(SAMPLE,[142])},142,root)
            self.assertEqual(data['strategic_region'],12);self.assertEqual(data['conditions'],['snow'])
            self.assertEqual(choose_map('plains',weather=data)[0],'multi/1v1_winter_fields')

    def test_winter_depends_on_snow_not_only_cold_and_preserves_terrain(self):
        cfg=config()
        normal=choose_map('plains',cfg=cfg)[0]
        self.assertEqual(choose_map('plains',cfg=cfg,weather={'temperature':-20,'snow_cover':0})[0],normal)
        for weather in ({'snow_cover':80},{'conditions':['snow']},{'conditions':['blizzard']}):
            self.assertEqual(choose_map('plains',cfg=cfg,weather=weather)[0],'multi/1v1_winter_fields')
        path,note=choose_map('forest',cfg=cfg,weather={'snow_cover':1})
        self.assertEqual(path,'multi/1v1_winter_hills');self.assertIn('approximation',note)
        cfg['winter_maps']={}
        with self.assertRaises(BridgeError):choose_map('plains',cfg=cfg,weather={'snow_cover':1})
