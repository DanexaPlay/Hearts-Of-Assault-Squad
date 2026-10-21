import tempfile,unittest
from pathlib import Path
from bridge.hoi import vanilla_metadata
from bridge.core import choose_map,config

class CityMapsTests(unittest.TestCase):
    def test_major_city_overrides_plain_tactical_map_and_retains_snow(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'map').mkdir();(root/'history/states').mkdir(parents=True)
            (root/'map/definition.csv').write_text('3134;0;0;0;land;false;plains;1\n142;0;0;0;land;false;plains;1\n6181;0;0;0;land;false;plains;1\n')
            (root/'history/states/213.txt').write_text('state={id=213 history={victory_points={3134 5} victory_points={6181 1}} provinces={142 3134 6181}}')
            campaign={'mods':[],'weather':{'provinces':{'3134':{'known':True,'snow_cover':80}},'regions':{}}}
            city=vanilla_metadata(campaign,3134,root)
            self.assertEqual(city['terrain'],'urban');self.assertEqual(city['base_terrain'],'plains')
            self.assertEqual(city['victory_point_value'],5)
            self.assertEqual(choose_map(city['terrain'],cfg=config(),weather=city['weather'])[0],'multi/1v1_winter_town')
            self.assertEqual(vanilla_metadata(campaign,142,root)['terrain'],'plains')
            self.assertEqual(vanilla_metadata(campaign,6181,root)['terrain'],'plains')
