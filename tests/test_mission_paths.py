import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from bridge.core import BridgeError,write_json,digest
from bridge.mission_paths import mission_path,assign_mission_path,installed_mission
from bridge.transition import install_generated_mod
from bridge.gem import terminal_autosave_winner
from bridge.map_resources import bind_land,validate_land_binding


class MissionPathTests(unittest.TestCase):
    def test_explicit_land_binds_all_native_assets_instead_of_launcher_relative_names(self):
        original='{map {Land {Position 0 0}} {Clips {pather 0 0 1000 1000}}}'
        definition='{land {Skeleton {bone "map" {VolumeView "map.ply" {Ground}}}} {extender "land" {Heightmap "map.net"}} {extender "grass" {Grass "map.grs"}}}'
        bound=bind_land(original,definition,'multi/1v1_road')
        validate_land_binding(bound,'multi/1v1_road')
        self.assertNotIn('"map.ply"',bound)
        self.assertIn('{pather 0 0 1000 1000}',bound)
        with self.assertRaises(BridgeError):validate_land_binding(bound,'multi/1v1_spring')
        with self.assertRaises(BridgeError):bind_land(original,definition,'../outside')

    def test_native_archive_link_is_scoped_and_hash_verified(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';target=root/'HOI4_MoW_Bridge'
            base=source/'resource/map/single/hmb/battle';base.mkdir(parents=True)
            (source/'mod.info').write_text('bridge');(base/'0.mi').write_text('mission')
            namespace='multi/1v1_road';wrapper=('(include "/map/'+namespace+'/map")\n').encode('utf8')
            (base/'map').write_bytes(wrapper)
            meta={'battle_id':'a'*32,'resource_path':namespace,'native_archive_source':True,'map_link_sha256':digest(wrapper)}
            write_json(source/'hmb-map-link.json',meta)
            self.assertFalse(install_generated_mod(source,target,root/'good')['requires_engine_restart'])
            self.assertFalse((target/'resource/map/multi/1v1_road/map').exists())
            for changed in ({**meta,'resource_path':'../outside'},{**meta,'map_link_sha256':'bad'}):
                write_json(source/'hmb-map-link.json',changed)
                with self.assertRaises(BridgeError):install_generated_mod(source,target,root/'bad')

    def test_linked_geometry_changes_without_replacing_cached_assets_or_requesting_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/'HOI4_MoW_Bridge'
            legacy=target/'resource/map/single/hmb/battle';legacy.mkdir(parents=True)
            (legacy/'map').write_text('old winter descriptor');(legacy/'map.ply').write_text('old cached ground')
            for index,terrain in enumerate(('summer','winter')):
                source=root/str(index);base=source/'resource/map/single/hmb/battle';base.mkdir(parents=True)
                identifier=str(index)*32;namespace='single/hmb/resources_'+identifier
                assets=source/('resource/map/'+namespace);assets.mkdir(parents=True)
                (assets/'map').write_text(terrain);(assets/'map.ply').write_text(terrain)
                (source/'mod.info').write_text('bridge');(base/'0.mi').write_text('new mission')
                wrapper=('(include "/map/'+namespace+'/map")\n').encode('utf8');(base/'map').write_bytes(wrapper)
                write_json(source/'hmb-map-link.json',{'battle_id':identifier,'resource_path':namespace,'map_link_sha256':digest(wrapper)})
                report=install_generated_mod(source,target,root/('install_'+str(index)))
                self.assertFalse(report['requires_engine_restart'])
                self.assertEqual((legacy/'map.ply').read_text(),'old cached ground')
            self.assertEqual((target/'resource/map/single/hmb/resources_00000000000000000000000000000000/map.ply').read_text(),'summer')

    def package(self,root,identifier,map_data):
        folder='battle_'+identifier
        base=root/'resource/map/single/hmb'/folder;base.mkdir(parents=True)
        (root/'mod.info').write_text('bridge')
        for name,data in [('0.mi','mission '+identifier),('map.ply',map_data),('interface.set','menu')]:
            (base/name).write_text(data)
        return base

    def test_paths_are_bound_to_uuid_and_legacy_remains_readable(self):
        b={'id':'a'*32};self.assertEqual(mission_path(b),'single/hmb/battle')
        self.assertEqual(assign_mission_path(b),'single/hmb/battle_'+'a'*32)
        for path in ('../../outside','single/hmb/battle_'+'b'*32,'single/hmb/battle_a'):
            with self.assertRaises(BridgeError):mission_path({**b,'mission_path':path})
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(BridgeError):installed_mission(folder,{'mission_relative_path':'../0.mi'})

    def test_different_maps_get_immutable_paths_without_restart_and_hide_only_old_menu(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/'HOI4_MoW_Bridge'
            legacy=target/'resource/map/single/hmb/battle';legacy.mkdir(parents=True)
            (legacy/'interface.set').write_text('legacy menu');(legacy/'map.ply').write_text('legacy map')
            one=self.package(root/'one','a'*32,'summer');two=self.package(root/'two','b'*32,'winter')
            first=install_generated_mod(root/'one',target,root/'first')
            self.assertFalse(first['requires_engine_restart']);self.assertTrue(first['unique_mission_resources'])
            old=installed_mission(target,first).parent
            second=install_generated_mod(root/'two',target,root/'second')
            self.assertFalse(second['requires_engine_restart'])
            self.assertNotEqual(first['mission_relative_path'],second['mission_relative_path'])
            self.assertEqual((old/'map.ply').read_text(),'summer')
            self.assertTrue((old/'0.mi').exists());self.assertFalse((old/'interface.set').exists())
            self.assertTrue(installed_mission(target,second).parent.joinpath('interface.set').exists())
            self.assertEqual((legacy/'map.ply').read_text(),'legacy map')
            self.assertFalse((legacy/'interface.set').exists())
            self.assertTrue((root/'second/install-backup'/old.relative_to(target.resolve())/'interface.set').exists())
            (two/'map.ply').write_text('changed under same UUID')
            with self.assertRaises(BridgeError):install_generated_mod(root/'two',target,root/'collision')
            self.assertEqual((installed_mission(target,second).parent/'map.ply').read_text(),'winter')

    def test_failed_hiding_rolls_back_new_resources_and_preserves_old_menu(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/'HOI4_MoW_Bridge'
            one=self.package(root/'one','a'*32,'summer');two=self.package(root/'two','b'*32,'winter')
            first=install_generated_mod(root/'one',target,root/'first');old=installed_mission(target,first).parent/'interface.set'
            original=Path.unlink
            def fail(path,*args,**kwargs):
                if path==old:raise PermissionError('fixture denial')
                return original(path,*args,**kwargs)
            with patch.object(Path,'unlink',fail):
                with self.assertRaises(PermissionError):install_generated_mod(root/'two',target,root/'failure')
            self.assertTrue(old.exists())
            self.assertFalse((target/two.relative_to(root/'two')/'0.mi').exists())

    def test_terminal_result_requires_both_exact_new_path_and_uuid(self):
        b={'id':'a'*32};assign_mission_path(b)
        game='{game {Threads {trigger "hmb_time_win_attacker" {current "/3/"} {state "/3/" {delay 1}}}}}'
        def entry(path,identifier):return '{"'+path+':0" {outro "HMB '+identifier+'\\nПобеда"}}'
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'game_progress.set'
            for text,valid in [(entry('single/hmb/battle',b['id']),False),
                               (entry(b['mission_path'],'b'*32),False),
                               (entry(b['mission_path'],b['id']),True)]:
                path.write_text(text,encoding='utf8')
                if valid:self.assertEqual(terminal_autosave_winner(b,game,path)[0],'attacker')
                else:
                    with self.assertRaises(BridgeError):terminal_autosave_winner(b,game,path)
