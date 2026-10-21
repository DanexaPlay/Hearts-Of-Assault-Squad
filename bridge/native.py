"""Local API adapter for the verified hoi4_lua v0.5 runtime.

No keyboard, window focus, or screenshot recognition. Mutating requests are
never retried: an HTTP timeout can leave a command queued in the game.
"""
import json
import re
import urllib.error
import urllib.request
from .core import BridgeError, write_json


class NativeHOI:
    VERSION = '1.19.3.0-c01a3d50'

    def __init__(self, port=17389):
        if not isinstance(port, int) or not 1024 <= port <= 65535:
            raise BridgeError('Invalid native bridge port')
        self.url = f'http://127.0.0.1:{port}'
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, route, body=None, timeout=5):
        req = urllib.request.Request(self.url + route,
            data=None if body is None else body.encode('utf8'),
            headers={'Content-Type': 'text/plain; charset=utf-8'})
        try:
            with self.opener.open(req, timeout=timeout) as response:
                data = response.read(1048577)
            if len(data) > 1048576:
                raise BridgeError('Oversized native response')
            result = json.loads(data)
        except (OSError, ValueError, urllib.error.URLError) as error:
            raise BridgeError('Native HOI4 request failed; command will not be retried: ' + str(error)) from error
        if not isinstance(result, dict) or result.get('ok') is not True:
            raise BridgeError('Native HOI4 rejected request: ' + str(result))
        return result

    def health(self):
        state = self.request('/health')
        if state.get('version') != self.VERSION:
            raise BridgeError('Unsupported native HOI4 version')
        if state.get('session_active') is not True:
            raise BridgeError('Native HOI4 has no loaded campaign')
        if type(state.get('paused')) is not bool or type(state.get('game_hour')) is not int:
            raise BridgeError('Invalid native game state')
        return state

    def ensure_paused(self):
        before = self.health()
        if before['paused']:
            return before
        self.request('/game/pause', '1', timeout=15)
        after = self.health()
        if not after['paused']:
            raise BridgeError('Native pause could not be verified')
        return after

    def capture(self, transfer):
        from pathlib import Path
        pending = transfer.pending
        if not pending or pending['status'] != 'waiting_snapshot':
            raise BridgeError('No pending native capture')
        if pending.get('native_save_name'):
            raise BridgeError('Native save already requested; refusing a second command')
        session = Path(pending['path'])
        name = 'HMB_transition_' + session.name
        if not re.fullmatch(r'HMB_transition_[0-9a-f]{32}', name):
            raise BridgeError('Invalid native save name')
        if list(transfer.saves.glob(name + '*.hoi4')):
            raise BridgeError('Native snapshot name already exists')
        before = self.ensure_paused()
        speed_normalization=None
        if before.get('speed',0)!=0:
            # A paused engine may retain speed 1..5 in its text-save header.
            # Keep strict speed=0 snapshot validation by explicitly stopping
            # the native clock before issuing the one-shot save command.
            response=self.request('/lua','hoi4.game_set_speed(0); return true',timeout=15)
            stopped=self.health()
            if (not stopped['paused'] or stopped.get('speed')!=0 or
                    stopped['game_hour']!=before['game_hour'] or stopped.get('date')!=before.get('date')):
                raise BridgeError('Zero-speed paused capture could not be verified')
            speed_normalization={'before':before,'response':response,'after':stopped}
            before=stopped
        if pending['request'].get('selection')=='native_v1':
            selected=self.combat_selection(pending['request'],before)
            pending['selected_combat']=selected
            pending['request'].update(combat=selected['combat'],province=str(selected['province']))
        # Persist intention before a command can be queued; no retry on restart.
        pending.update(native_save_name=name, native_health=before)
        transfer._record()
        response = self.request('/console', 'savegame ' + name, timeout=65)
        after = self.health()
        if not after['paused'] or after.get('speed',0)!=0 or after['game_hour'] != before['game_hour']:
            raise BridgeError('Campaign changed during native capture')
        evidence = {'before': before, 'command': 'savegame ' + name,
                    'response': response, 'after': after}
        if speed_normalization:evidence['speed_normalization']=speed_normalization
        write_json(session / 'native-capture.json', evidence)
        pending['native_capture_verified'] = True
        transfer._record()
        return evidence

    def combat_selection(self,request,state):
        country=request.get('country');seq=request.get('seq')
        if not country or not re.fullmatch(r'[A-Z][A-Z0-9]{2}',country) or not seq or not re.fullmatch(r'\d+',seq):
            raise BridgeError('Combat selection requires a country and button sequence')
        response=self.request('/lua','assert(HMB_SELECTION,"Restart HOI4 with the updated combat button"); return HMB_SELECTION.read('+json.dumps(country)+','+str(int(seq))+')')
        try:record=json.loads(response['result'])
        except (KeyError,TypeError,ValueError) as error:raise BridgeError('Invalid native combat selection response') from error
        if not isinstance(record,dict) or record.get('error'):
            raise BridgeError('Cannot identify the clicked combat: '+str(record.get('error') if isinstance(record,dict) else record))
        if (record.get('country'),record.get('seq'),record.get('game_hour'),record.get('source'))!=(country,int(seq),state['game_hour'],'combat_button_effect_v1'):
            raise BridgeError('Combat selection does not match this button press or game hour')
        if not re.fullmatch(r'\d+:62',str(record.get('combat',''))) or type(record.get('province')) is not int or record['province']<=0 or not record.get('campaign_id'):
            raise BridgeError('Invalid combat selection identity')
        return record

    def organization_snapshot(self,b,hour):
        from pathlib import Path
        from .live import lua
        from .readiness import organization_ratio
        state=self.health()
        if not state['paused'] or state['game_hour']!=hour or state['date']!=b['snapshot_date']:
            raise BridgeError('Campaign changed before organisation read')
        units={d['id']:True for side in ('attacker','defender') for d in b[side]['divisions']}
        self.request('/lua',Path(__file__).with_name('live_runtime.lua').read_text(encoding='utf8'))
        response=self.request('/lua','return HMB_LIVE.json(HMB_LIVE.organization('+lua({'units':units,'provinces':{}})+'))')
        try:record=json.loads(response['result'])
        except (KeyError,TypeError,ValueError) as error:raise BridgeError('Invalid organisation response') from error
        if (not isinstance(record,dict) or not isinstance(record.get('units'),dict) or
            record.get('campaign_id')!=b['campaign_id'] or record.get('hour')!=hour or set(record['units'])!=set(units)):
            raise BridgeError('Organisation read belongs to another campaign, hour or unit set')
        checked={**b,'organization_snapshot':record['units'],'organization_scaling_required':True}
        for side in ('attacker','defender'):
            for d in b[side]['divisions']:organization_ratio(checked,d)
        after=self.health()
        if not after['paused'] or after['game_hour']!=hour:raise BridgeError('Campaign changed during organisation read')
        return record
