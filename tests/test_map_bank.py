import tempfile,unittest
from unittest.mock import Mock,patch
from pathlib import Path
from bridge.core import BridgeError,digest,write_json
from bridge.mission_paths import map_slot,mission_path
from bridge.map_bank import validate_installed_bank,validate_slot_package
from bridge.transition import install_generated_mod

class MapBankTests(unittest.TestCase):
    def test_new_custom_infantry_resource_restarts_once_then_reuses_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';target=root/'HOI4_MoW_Bridge'
            slot,_=self.package(source,'multi/1v1_road')
            install_generated_mod(source,target,root/'setup',initialize_bank=True)
            write_json(target/'hmb-map-bank.json',{'schema':1,'slots':[slot]})
            receipt=target/'.hmb-engine-restart.json';receipt.unlink()
            breed=source/'resource/set/breed/hmb/ger_infantry_3.set';breed.parent.mkdir(parents=True);breed.write_text('new infantry equipment')
            first=install_generated_mod(source,target,root/'first')
            self.assertTrue(first['requires_engine_restart'])
            self.assertEqual(first['changed_breed_resources'],['resource/set/breed/hmb/ger_infantry_3.set'])
            receipt.unlink() # Simulated confirmed cold launch.
            second=install_generated_mod(source,target,root/'second')
            self.assertFalse(second['requires_engine_restart'])
            self.assertEqual(second['changed_breed_resources'],[])

    def test_warm_launcher_selects_the_installed_slot_and_passes_the_whole_catalogue(self):
        from bridge.mow_launch import start
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'HOI4_MoW_Bridge';slots=[]
            for index,name in enumerate(('multi/1v1_road','multi/1v1_spring')):
                source=root/str(index);slot,_=self.package(source,name);slots.append(slot)
                installation=install_generated_mod(source,target,root/('setup'+str(index)),initialize_bank=True)
            slots.sort(key=lambda s:s['mission_path']);write_json(target/'hmb-map-bank.json',{'schema':1,'slots':slots})
            installation['requires_engine_restart']=False
            transfer=Mock();transfer.pending={'status':'ready','path':str(root),'installation':installation}
            transfer.collect_loaded.return_value=None;transfer.collect_final.return_value=None
            with patch('bridge.launch_native.running',side_effect=lambda name:name=='mowas_2.exe'),patch('bridge.desktop.GameDesktop') as desktop:
                desktop.return_value.ready_window.return_value=True
                state=start(transfer,{'mow':str(root),'mow_log':str(root/'game.log')},root)
                selected=desktop.return_value.navigate_mission.call_args.kwargs
            self.assertEqual(state['launch_method'],'reuse_running_game')
            self.assertEqual(selected['mission_slot'],map_slot('multi/1v1_spring'))
            self.assertEqual(selected['registered_slots'],[s['mission_path'] for s in slots])

    def test_loader_refuses_an_uncalibrated_bank_button(self):
        from bridge.desktop import bank_button
        slot=map_slot('multi/1v1_road')
        with self.assertRaises(BridgeError):bank_button({},slot)
        with self.assertRaises(BridgeError):bank_button({'mow_map_bank':{'missions':{slot:[850,9999]}}},slot)
        self.assertEqual(bank_button({'mow_map_bank':{'missions':{slot:[850,300]}}},slot),(850,300))
        with self.assertRaises(BridgeError):bank_button({'mow_map_bank':{'missions':{slot:[850,300]}}},slot,[slot,map_slot('multi/1v1_spring')])

    def package(self,root,name):
        virtual=map_slot(name);base=root/('resource/map/'+virtual);base.mkdir(parents=True)
        for filename,data in [('map','native '+name),('map.ply','mesh '+name),('map.net','heights '+name),('0.mi','fixture'),('interface.set','menu')]:
            (base/filename).write_text(data)
        label=root/('localization/mission/'+virtual+'.lng');label.parent.mkdir(parents=True);label.write_text('label')
        (root/'mod.info').write_text('bridge')
        immutable={p.relative_to(root).as_posix():digest(p.read_bytes()) for p in base.iterdir() if p.name not in ('0.mi','interface.set')}
        slot={'schema':1,'source_map':name,'mission_path':virtual,'immutable':immutable}
        write_json(root/'hmb-map-slot.json',slot)
        return slot,base

    def test_slot_is_bound_to_source_map_not_battle_id(self):
        path=map_slot('multi/1v1_road')
        self.assertEqual(mission_path({'id':'a'*32,'map_source':'multi/1v1_road','mission_path':path}),path)
        with self.assertRaises(BridgeError):mission_path({'map_source':'multi/1v1_spring','mission_path':path})
        with self.assertRaises(BridgeError):map_slot('../outside')

    def test_preinstalled_slots_keep_distinct_geometry_and_survive_payload_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'HOI4_MoW_Bridge';slots=[]
            for index,name in enumerate(('multi/1v1_road','multi/1v1_spring')):
                source=root/str(index);slot,base=self.package(source,name);slots.append(slot)
                install_generated_mod(source,target,root/('setup'+str(index)),initialize_bank=True)
            slots.sort(key=lambda s:s['mission_path']);write_json(target/'hmb-map-bank.json',{'schema':1,'slots':slots})
            validate_installed_bank(target)
            (target/'.hmb-engine-restart.json').unlink()
            source=root/'0';base=source/('resource/map/'+map_slot('multi/1v1_road'))
            (base/'0.mi').write_text('new battle')
            report=install_generated_mod(source,target,root/'update')
            self.assertFalse(report['requires_engine_restart'])
            self.assertEqual(report['unchanged_terrain_files'],3)
            self.assertFalse((root/'update/install-backup'/base.relative_to(source)/'map.net').exists())
            for slot in slots:
                self.assertTrue((target/('resource/map/'+slot['mission_path']+'/interface.set')).is_file())
                for rel,expected in slot['immutable'].items():self.assertEqual(digest((target/rel).read_bytes()),expected)
            (base/'map.net').write_text('tampered heights')
            with self.assertRaises(BridgeError):install_generated_mod(source,target,root/'bad')
            self.assertEqual((target/base.relative_to(source)/'0.mi').read_text(),'new battle')

    def test_unregistered_or_damaged_bank_is_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';target=root/'HOI4_MoW_Bridge'
            slot,base=self.package(source,'multi/1v1_road')
            with self.assertRaises(BridgeError):install_generated_mod(source,target,root/'missing')
            self.assertFalse(target.exists())
            install_generated_mod(source,target,root/'setup',initialize_bank=True)
            write_json(target/'hmb-map-bank.json',{'schema':1,'slots':[slot]})
            (target/next(iter(slot['immutable']))).write_text('corrupt')
            with self.assertRaises(BridgeError):install_generated_mod(source,target,root/'corrupt')

    def test_returning_to_legacy_marks_menu_change_for_cold_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'slot';target=root/'HOI4_MoW_Bridge'
            slot,base=self.package(source,'multi/1v1_road')
            install_generated_mod(source,target,root/'setup',initialize_bank=True)
            (target/'.hmb-engine-restart.json').unlink()
            legacy=root/'legacy';folder=legacy/'resource/map/single/hmb/battle';folder.mkdir(parents=True)
            (legacy/'mod.info').write_text('bridge');(folder/'0.mi').write_text('legacy');(folder/'interface.set').write_text('menu')
            report=install_generated_mod(legacy,target,root/'restore')
            self.assertTrue(report['requires_engine_restart'])
            self.assertTrue((target/('resource/map/'+slot['mission_path']+'/map.ply')).is_file())
