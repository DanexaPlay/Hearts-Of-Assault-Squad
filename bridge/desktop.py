"""User-run game UI driver. Inputs are scoped to exact game executables.

The assistant tests game actions through Computer Use; this application module
is never a fallback tool for controlling the user's desktop during development.
"""
import ctypes,time,os,math
from ctypes import wintypes as W
from pathlib import Path
from .core import BridgeError,read_json,write_json

SIZE=(1707,1067)

def bank_button(profile,mission_slot,registered_slots=None):
    spec=profile.get('mow_map_bank',{})
    if registered_slots is not None and set(spec.get('missions',{}))!=set(registered_slots):
        raise BridgeError('Installed map catalogue differs from the calibrated menu; no mission was clicked')
    point=spec.get('missions',{}).get(mission_slot)
    if not isinstance(point,list) or len(point)!=2 or not all(isinstance(v,int) for v in point):
        raise BridgeError('Map-bank menu is not calibrated for this slot; no mission was clicked')
    if not (0<point[0]<SIZE[0] and 0<point[1]<SIZE[1]):raise BridgeError('Invalid map-bank button coordinates')
    return tuple(point)

def scene_matches(image,reference,box,tolerance=5):
    return scene_difference(image,reference,box)<=tolerance

def scene_difference(image,reference,box):
    from PIL import ImageChops,ImageStat,ImageFilter
    image=image.convert('RGB').resize(SIZE)
    reference=reference.convert('RGB').resize(SIZE)
    image=image.crop(box);reference=reference.crop(box)
    # Windows capture and native desktop capture use different interpolation.
    # Compare blurred structure instead of requiring identical antialias pixels.
    a=list(image.convert('L').filter(ImageFilter.GaussianBlur(1.5)).get_flattened_data())
    b=list(reference.convert('L').filter(ImageFilter.GaussianBlur(1.5)).get_flattened_data())
    am=sum(a)/len(a);bm=sum(b)/len(b)
    av=sum((x-am)**2 for x in a);bv=sum((x-bm)**2 for x in b)
    if min(av,bv)<len(a):
        return max(ImageStat.Stat(ImageChops.difference(image,reference)).mean)
    correlation=sum((x-am)*(y-bm) for x,y in zip(a,b))/math.sqrt(av*bv)
    return (1-max(-1,min(1,correlation)))*100

class GameDesktop:
    def __init__(self,cfg,root):
        if os.name!='nt':raise BridgeError('Game UI driver requires Windows')
        self.cfg=cfg;self.root=Path(root)
        local_profile=self.root/'runtime/ui-reference/profile.json'
        self.profile=read_json(local_profile) if local_profile.is_file() else {}
        mow_profile=self.root/'assets/mow-ui/profile.json'
        if mow_profile.exists():self.profile.update(read_json(mow_profile))
        self.u=ctypes.WinDLL('user32',use_last_error=True);self.k=ctypes.WinDLL('kernel32',use_last_error=True)
        self.u.SetProcessDPIAware()
        self.u.GetForegroundWindow.restype=W.HWND
        self.u.IsWindow.argtypes=[W.HWND];self.u.SetForegroundWindow.argtypes=[W.HWND]
        self.u.PostMessageW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM];self.u.PostMessageW.restype=W.BOOL
        self.u.IsWindowVisible.argtypes=[W.HWND];self.u.ShowWindow.argtypes=[W.HWND,ctypes.c_int]
        self.u.IsIconic.argtypes=[W.HWND];self.u.IsIconic.restype=W.BOOL
        self.u.GetWindowRect.argtypes=[W.HWND,ctypes.POINTER(W.RECT)]
        self.u.GetWindowThreadProcessId.argtypes=[W.HWND,ctypes.POINTER(W.DWORD)]
        self.k.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];self.k.OpenProcess.restype=W.HANDLE
        self.k.CloseHandle.argtypes=[W.HANDLE]
        self.k.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,ctypes.POINTER(W.DWORD)]
        self.handle=None;self.expected=None
    def executable(self,handle):
        pid=W.DWORD();self.u.GetWindowThreadProcessId(handle,ctypes.byref(pid))
        process=self.k.OpenProcess(0x1000,False,pid.value)
        if not process:return None
        try:
            size=W.DWORD(32768);name=ctypes.create_unicode_buffer(size.value)
            if not self.k.QueryFullProcessImageNameW(process,0,name,ctypes.byref(size)):return None
            return Path(name.value).resolve()
        finally:self.k.CloseHandle(process)
    def windows_for(self,game):
        expected=(Path(self.cfg[game])/('hoi4.exe' if game=='hoi4' else 'mowas_2.exe')).resolve()
        found=[];callback=ctypes.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
        @callback
        def visit(handle,_):
            if self.u.IsWindowVisible(handle) and self.executable(handle)==expected:found.append(handle)
            return True
        self.u.EnumWindows(visit,0)
        return found
    def ready_window(self,game):
        # MoW's splash has a different size and may disappear/recreate its HWND.
        # Do not activate it or send input until the full-sized window exists.
        found=self.windows_for(game)
        if len(found)!=1:return False
        if self.u.IsIconic(found[0]):return True # activate restores before matching
        rect=W.RECT()
        if not self.u.GetWindowRect(found[0],ctypes.byref(rect)):return False
        width,height=rect.right-rect.left,rect.bottom-rect.top
        return width>=800 and height>=600 and abs(width/height-SIZE[0]/SIZE[1])<=.03
    def activate(self,game):
        self.expected=(Path(self.cfg[game])/('hoi4.exe' if game=='hoi4' else 'mowas_2.exe')).resolve()
        found=self.windows_for(game)
        if len(found)!=1:raise BridgeError('Expected one running '+game+' game window; found '+str(len(found)))
        self.handle=found[0];self.u.ShowWindow(self.handle,9);self.u.SetForegroundWindow(self.handle)
        time.sleep(.5);self.guard()
    def guard(self):
        if self.u.GetAsyncKeyState(0x1b)&0x8000:raise BridgeError('UI transfer cancelled with Escape')
        if not self.handle or self.u.GetForegroundWindow()!=self.handle or self.executable(self.handle)!=self.expected:
            raise BridgeError('Game lost foreground focus; UI transfer stopped')
    def capture(self):
        from PIL import ImageGrab
        self.guard();rect=W.RECT();self.u.GetWindowRect(self.handle,ctypes.byref(rect))
        self.bounds=(max(0,rect.left),max(0,rect.top),min(self.u.GetSystemMetrics(0),rect.right),min(self.u.GetSystemMetrics(1),rect.bottom))
        x,y,r,b=self.bounds
        if r-x<800 or b-y<600:raise BridgeError('Game window is too small for the calibrated UI')
        if abs((r-x)/(b-y)-SIZE[0]/SIZE[1])>.03:raise BridgeError('Game aspect ratio differs from the calibrated UI')
        return ImageGrab.grab(bbox=self.bounds).resize(SIZE)
    def matches(self,scene):
        from PIL import Image
        spec=self.profile[scene]
        captured=self.capture();self.last_capture=captured
        base=self.root/('assets/mow-ui' if spec.get('bundled') else 'runtime/ui-reference')
        candidates=[]
        for filename in [spec['reference']]+spec.get('alternate_references',[]):
            with Image.open(base/filename) as reference:
                differences=[scene_difference(captured,reference,tuple(box)) for box in spec.get('boxes',[spec['box']])]
            candidates.append((max(differences),filename,differences))
        _,filename,differences=min(candidates)
        self.last_match={'scene':scene,'reference':filename,'differences':differences,'tolerance':spec.get('tolerance',5),'bounds':self.bounds}
        return all(d<=self.last_match['tolerance'] for d in differences)
    def diagnose(self,error):
        destination=self.root/'runtime/ui-diagnostics';destination.mkdir(parents=True,exist_ok=True)
        if getattr(self,'last_capture',None) is not None:self.last_capture.save(destination/'stopped.png')
        foreground=self.u.GetForegroundWindow()
        write_json(destination/'stopped.json',{'error':str(error),'last_match':getattr(self,'last_match',None),
            'expected_executable':str(self.expected),'target_handle':self.handle,
            'foreground_handle':foreground,'foreground_executable':str(self.executable(foreground)),
            'recorded_at_ns':time.time_ns()})
    def wait(self,scene,timeout=8):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            if self.matches(scene):return
            time.sleep(.25)
        raise BridgeError('Expected UI did not appear: '+scene)
    def click(self,scene,x,y):
        if not self.matches(scene):raise BridgeError('Unexpected screen before click: '+scene)
        self.guard();left,top,right,bottom=self.bounds
        self.u.SetCursorPos(round(left+x*(right-left)/SIZE[0]),round(top+y*(bottom-top)/SIZE[1]))
        self.guard();self.u.mouse_event(2,0,0,0,0)
        try:time.sleep(.15)
        finally:self.u.mouse_event(4,0,0,0,0)
        time.sleep(.3)
    def key(self,key):
        self.guard();self.u.keybd_event(key,0,0,0)
        try:time.sleep(.15)
        finally:self.u.keybd_event(key,0,2,0)
    def save_snapshot(self):
        self.activate('hoi4')
        # The triggered event/menu can already be open. Never toggle speed.
        if not self.matches('hoi_menu') and not self.matches('hoi_save'):
            self.wait('hoi_topbar')
            if not self.matches('hoi_paused'):
                self.key(0x20);self.wait('hoi_paused')
            self.key(0x1b)
        if not self.matches('hoi_save'):
            self.wait('hoi_menu');self.click('hoi_menu',850,403)
        self.wait('hoi_save')
        # Use native default name. Back up all existing local saves before this
        # call in the coordinator. An overwrite prompt is never confirmed here.
        self.click('hoi_save',923,754)
    def mission_menu_ready(self):
        self.activate('mow')
        return self.matches('mow_campaign')
    def confirm_mow_menu(self,restore_focus=False):
        """Positive scene-exit evidence; a victory overlay is not a menu."""
        previous=self.u.GetForegroundWindow() if restore_focus else None
        try:
            self.activate('mow')
            names=['mow_main','mow_single','mow_campaigns','mow_campaign']
            if 'mow_map_bank' in getattr(self,'profile',{}):names.append('mow_map_bank')
            found=[scene for scene in names if self.matches(scene)]
            if 'mow_map_bank' in found and 'mow_campaign' in found:found.remove('mow_campaign')
            if len(found)!=1:raise BridgeError('Leave the completed MoW mission and return to its menu before another transfer')
            return {'kind':'recognized_mow_menu','scene':found[0],'executable':str(self.expected),
                'verified_at_ns':time.time_ns()}
        finally:
            if previous and previous!=self.handle and self.u.IsWindow(previous) and self.u.GetForegroundWindow()==self.handle:
                self.u.SetForegroundWindow(previous)
    def close_mow_menu(self):
        """Graceful close for a changed map; never close a running mission."""
        proof=self.confirm_mow_menu()
        if not self.matches(proof['scene']):raise BridgeError('MoW left its menu before the map-cache restart')
        self.guard()
        if not self.u.PostMessageW(self.handle,0x0010,0,0):raise BridgeError('Could not request a normal MoW exit')
        return proof
    def load_mission(self):
        self.activate('mow');self.wait('mow_campaign')
        self.click('mow_campaign',850,251)
        # Initial autosave is the load acknowledgment. Never send Space blindly:
        # it can pause an already running mission instead of dismissing an intro.
    def navigate_mission(self,timeout=120,progress=None,acknowledged=None,mission_slot=None,registered_slots=None):
        """User-run menu route; each click requires its observed source screen."""
        progress=progress or (lambda stage:None)
        campaign='mow_map_bank' if mission_slot else 'mow_campaign'
        button=bank_button(self.profile,mission_slot,registered_slots) if mission_slot else (850,251)
        progress('activate_menu')
        self.activate('mow')
        route=[('mow_main',850,233,'mow_single'),
               ('mow_single',850,281,'mow_campaigns'),
               ('mow_campaigns',850,514,campaign)]
        names=[step[0] for step in route]+[campaign]
        end=time.monotonic()+timeout
        while True:
            if acknowledged and acknowledged():
                progress('engine_start_acknowledged');return
            matches=[scene for scene in names if self.matches(scene)]
            if matches or time.monotonic()>=end:break
            time.sleep(.5)
        if len(matches)!=1:
            raise BridgeError('MoW must be at its main menu or the bridge mission selection screen')
        start=names.index(matches[0])
        for scene,x,y,next_scene in route[start:]:
            progress('select_from_'+scene)
            self.click(scene,x,y);self.wait(next_scene,timeout=15)
        progress('select_battle')
        self.click(campaign,*button)
        progress('wait_for_start_prompt')
        end=time.monotonic()+120
        while time.monotonic()<end:
            if acknowledged and acknowledged():
                progress('engine_start_acknowledged');return
            scene='mow_start' if self.matches('mow_start') else 'mow_start_overlay' if self.matches('mow_start_overlay') else None
            if scene:
                progress('dismiss_start_prompt')
                # Native acknowledgment is checked again immediately before
                # input: a manually started battle must never receive Space.
                if (not acknowledged or not acknowledged()) and self.matches(scene):self.key(0x20)
                return
            time.sleep(.25)
        raise BridgeError('Expected UI did not appear: mow_start')
