import unittest
from pathlib import Path
from PIL import Image
from bridge.desktop import scene_matches,GameDesktop,SIZE
from bridge.core import BridgeError

class DesktopTests(unittest.TestCase):
    def test_cache_restart_never_closes_a_mission_or_a_changed_screen(self):
        from unittest.mock import Mock
        for menu,still_menu in ((False,False),(True,False),(True,True)):
            desktop=object.__new__(GameDesktop);desktop.u=Mock();desktop.handle=123;desktop.guard=Mock()
            desktop.confirm_mow_menu=Mock(return_value={'scene':'mow_main'})
            if not menu:desktop.confirm_mow_menu.side_effect=BridgeError('In mission')
            desktop.matches=lambda scene:still_menu
            if menu and still_menu:
                desktop.close_mow_menu();desktop.u.PostMessageW.assert_called_once_with(123,0x10,0,0)
            else:
                with self.assertRaises(BridgeError):desktop.close_mow_menu()
                desktop.u.PostMessageW.assert_not_called()

    def test_discord_bar_does_not_hide_the_alternate_loading_frame(self):
        from bridge.core import ROOT,read_json
        from PIL import ImageDraw
        desktop=object.__new__(GameDesktop);desktop.root=ROOT;desktop.profile=read_json(ROOT/'assets/mow-ui/profile.json');desktop.bounds=(0,0,*SIZE)
        with Image.open(ROOT/'assets/mow-ui/mow_start_overlay_sky.png') as im:captured=im.convert('RGB')
        ImageDraw.Draw(captured).rectangle((0,960,1706,1020),fill=(25,25,25))
        desktop.capture=lambda:captured
        self.assertFalse(desktop.matches('mow_start'))
        self.assertTrue(desktop.matches('mow_start_overlay'))
        desktop.capture=lambda:Image.new('RGB',SIZE,'black')
        self.assertFalse(desktop.matches('mow_start_overlay'))

    def test_menu_check_restores_previous_window_without_stealing_user_focus(self):
        from unittest.mock import Mock
        for foreground in (20,30):
            desktop=object.__new__(GameDesktop);desktop.u=Mock();desktop.handle=20;desktop.expected=Path('mowas_2.exe');desktop.activate=Mock()
            desktop.u.GetForegroundWindow.side_effect=[10,foreground];desktop.u.IsWindow.return_value=True
            desktop.matches=lambda scene:scene=='mow_main'
            desktop.confirm_mow_menu(restore_focus=True)
            if foreground==20:desktop.u.SetForegroundWindow.assert_called_once_with(10)
            else:desktop.u.SetForegroundWindow.assert_not_called()

    def test_real_loading_prompt_cross_capture_regression(self):
        from bridge.core import ROOT,read_json
        from PIL import ImageEnhance
        profile=read_json(ROOT/'assets/mow-ui/profile.json');spec=profile['mow_start']
        with Image.open(ROOT/'assets/mow-ui/mow_start_native.png') as im:native=im.convert('RGB')
        with Image.open(ROOT/'assets/mow-ui/mow_start.png') as im:sky=im.convert('RGB')
        # This actual failing capture differed by 7.48 at the prompt while the
        # first capture reference allowed 6. Both display the same start page.
        self.assertFalse(scene_matches(native,sky,tuple(spec['boxes'][1]),6))
        desktop=object.__new__(GameDesktop);desktop.root=ROOT;desktop.profile=profile;desktop.bounds=(0,0,1707,1067)
        for captured in [native,sky,ImageEnhance.Brightness(native).enhance(.8)]:
            desktop.capture=lambda:captured
            self.assertTrue(desktop.matches('mow_start'))
        self.assertEqual(spec['tolerance'],6)

    def test_loading_prompt_alternates_do_not_accept_main_menu_or_blank_screen(self):
        from bridge.core import ROOT,read_json
        desktop=object.__new__(GameDesktop);desktop.root=ROOT;desktop.profile=read_json(ROOT/'assets/mow-ui/profile.json');desktop.bounds=(0,0,1707,1067)
        with Image.open(ROOT/'assets/mow-ui/mow_main.png') as im:main=im.convert('RGB')
        for captured in [main,Image.new('RGB',SIZE,'black')]:
            desktop.capture=lambda:captured
            self.assertFalse(desktop.matches('mow_start'))

    def test_menu_dimming_needs_a_separate_live_game_reference(self):
        live=Image.new('RGB',SIZE,(100,100,100));dimmed=Image.new('RGB',SIZE,(75,75,75))
        self.assertFalse(scene_matches(live,dimmed,(1600,0,1694,70)))
        self.assertTrue(scene_matches(live,live,(1600,0,1694,70)))
    def test_matching_structure_tolerates_capture_brightness_but_not_another_layout(self):
        from PIL import ImageDraw,ImageEnhance
        reference=Image.new('RGB',SIZE,(60,60,60));draw=ImageDraw.Draw(reference)
        draw.rectangle((110,110,170,140),fill='white');draw.rectangle((200,150,270,180),fill='white')
        self.assertTrue(scene_matches(ImageEnhance.Brightness(reference).enhance(.7),reference,(100,100,300,200)))
        wrong=Image.new('RGB',SIZE,(60,60,60));ImageDraw.Draw(wrong).rectangle((150,100,180,195),fill='white')
        self.assertFalse(scene_matches(wrong,reference,(100,100,300,200)))
    def test_scene_match_rejects_wrong_screen_and_ignores_unrelated_regions(self):
        reference=Image.new('RGB',SIZE,(40,50,60));same=reference.copy()
        same.paste((255,0,0),(1000,700,1500,1000))
        self.assertTrue(scene_matches(same,reference,(100,100,300,200)))
        same.paste((200,200,200),(100,100,300,200))
        self.assertFalse(scene_matches(same,reference,(100,100,300,200)))
    def test_input_is_not_sent_when_foreground_guard_fails(self):
        desktop=object.__new__(GameDesktop)
        def reject():raise BridgeError('Game lost focus')
        desktop.guard=reject
        with self.assertRaises(BridgeError):desktop.key(32)
    def test_unknown_menu_prevents_coordinate_click(self):
        desktop=object.__new__(GameDesktop);desktop.matches=lambda scene:False
        with self.assertRaises(BridgeError):desktop.click('hoi_save',923,754)
