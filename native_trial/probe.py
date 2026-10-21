"""User-run, bounded native HOI4 pause/save trial. No UI automation."""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import struct
import subprocess
import time
import urllib.request
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parent
from bridge.core import config
GAME = pathlib.Path(config()['hoi4']) / 'hoi4.exe'
USER = pathlib.Path(config()['hoi4_user'])
SOURCE = USER / 'save games' / 'GER_1936_01_01_16_temp.hoi4'
PORT = 17389
SIGNATURE = (0x6AA123BB, 0x37EC000, 0x03534BB2)


def signature(path):
    with path.open('rb') as stream:
        head = stream.read(4096)
    pe = struct.unpack_from('<I', head, 0x3c)[0]
    if head[:2] != b'MZ' or head[pe:pe + 4] != b'PE\0\0':
        raise RuntimeError('Invalid executable header')
    return (struct.unpack_from('<I', head, pe + 8)[0],
            struct.unpack_from('<I', head, pe + 24 + 56)[0],
            struct.unpack_from('<I', head, pe + 24 + 64)[0])


def request(route, body=None, timeout=45):
    req = urllib.request.Request(f'http://127.0.0.1:{PORT}{route}',
                                 data=None if body is None else body.encode('utf-8'),
                                 headers={'Content-Type': 'text/plain; charset=utf-8'})
    # Local requests must not be sent through a configured network proxy.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout) as response:
        return json.load(response)


def validate():
    if signature(GAME) != SIGNATURE:
        raise RuntimeError('Unsupported HOI4 build; trial refused')
    manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['binaries'].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Binary hash mismatch: ' + name)
    config = json.loads((USER / 'dlc_load.json').read_text(encoding='utf-8-sig'))
    enabled = config.get('enabled_mods', [])
    if enabled != ['mod/hoi4_mow_bridge.mod']:
        raise RuntimeError('Trial requires only the existing HOI4 bridge mod enabled')
    if list((ROOT.parent / 'hoi4_mod').rglob('*.lua')):
        raise RuntimeError('Unexpected Lua scripts in the enabled bridge mod')
    if not SOURCE.is_file():
        raise RuntimeError('Test campaign is missing: ' + str(SOURCE))


def run():
    validate()
    processes = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq hoi4.exe', '/FO', 'CSV', '/NH'],
                               capture_output=True, text=True).stdout.lower()
    if 'hoi4.exe' in processes:
        raise RuntimeError('Close HOI4 first, then run this trial again. Men of War may stay open.')
    try:
        request('/health', timeout=2)
    except Exception:
        pass
    else:
        raise RuntimeError('Port 17389 is already in use by a native bridge; trial refused')
    session = ROOT / 'evidence' / datetime.now().strftime('%Y%m%d_%H%M%S')
    session.mkdir(parents=True)
    shutil.copy2(SOURCE, session / SOURCE.name)
    for name in ['settings.txt', 'dlc_load.json', 'pdx_settings.json']:
        if (USER / name).is_file():
            shutil.copy2(USER / name, session / name)
    for name in ['hoi4_bridge.log', 'game.log', 'error.log']:
        if (USER / 'logs' / name).is_file():
            shutil.copy2(USER / 'logs' / name, session / ('before_' + name))
    report = {'source': str(SOURCE), 'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
              'status': 'starting', 'pause_verified': False, 'save_verified': False}
    def record():
        (session / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    record()
    # Do not synchronize the user's mod list from the save header.
    args = [str(ROOT / 'hoi4_launcher.exe'), '--exe=' + str(GAME), '--no-mod-sync',
            '-start_save=' + SOURCE.stem, '-http=' + str(PORT)]
    print('Starting the separate test campaign. Waiting up to 8 minutes for loading...', flush=True)
    with (session / 'launcher.log').open('wb') as log:
        launcher = subprocess.Popen(args, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
                                    env={**os.environ,'HOI4_DLL_DEBUG':'1'},
                                    creationflags=0x08000000)
        try:
            deadline = time.monotonic() + 480
            health = None
            while time.monotonic() < deadline:
                try:
                    health = request('/health', timeout=5)
                    if health.get('session_active') is True:
                        break
                except Exception:
                    pass
                if launcher.poll() not in (None, 0):
                    raise RuntimeError('Native launcher failed; see launcher.log')
                time.sleep(1)
            else:
                raise RuntimeError('No loaded game session; see launcher.log and bridge logs')
            report['health_before'] = health
            version = str(health.get('version', ''))
            if '1.19.3' not in version:
                raise RuntimeError('Unexpected bridge version in health response: ' + version)
            for _ in range(2):
                response = request('/game/pause', '1')
                if response.get('ok') is not True:
                    raise RuntimeError('Pause command failed: ' + str(response))
                if request('/health').get('paused') is not True:
                    raise RuntimeError('Pause state not confirmed')
            report['pause_verified'] = True
            before = request('/health')
            time.sleep(3)
            after = request('/health')
            if before.get('game_hour') != after.get('game_hour'):
                raise RuntimeError('Game clock advanced while paused')
            report['health_paused'] = after
            if after.get('date') != '1936.1.1.16':
                raise RuntimeError('Unexpected campaign date; no save command sent: ' + str(after.get('date')))
            save_name = 'HMB_native_' + datetime.now().strftime('%Y%m%d_%H%M%S')
            report['requested_save'] = save_name
            report['save_response'] = request('/console', 'savegame ' + save_name, timeout=60)
            if report['save_response'].get('ok') is not True:
                raise RuntimeError('Native save command failed: ' + str(report['save_response']))
            # Do not retry a timed-out command: it may still be queued in the game.
            deadline = time.monotonic() + 90
            target = None
            last = None
            stable = 0
            while time.monotonic() < deadline:
                candidates = list((USER / 'save games').glob(save_name + '*.hoi4'))
                if candidates:
                    target = max(candidates, key=lambda p: p.stat().st_mtime_ns)
                    state = (target.stat().st_size, target.stat().st_mtime_ns)
                    stable = stable + 1 if state == last else 0
                    last = state
                    if state[0] > 1000 and stable >= 3:
                        break
                time.sleep(1)
            else:
                raise RuntimeError('Named save did not appear or stabilize; command will not be repeated')
            shutil.copy2(target, session / target.name)
            report['save_verified'] = True
            report['saved_file'] = str(target)
            report['saved_sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
            report['health_after'] = request('/health')
            report['source_unchanged'] = hashlib.sha256(SOURCE.read_bytes()).hexdigest() == report['source_sha256']
            if not report['source_unchanged'] or report['health_after'].get('paused') is not True:
                raise RuntimeError('Post-check failed; inspect report before continuing')
            report['status'] = 'passed'
            print('PASS: native pause and named background save confirmed. HOI4 remains paused.', flush=True)
        except Exception as error:
            report['status'] = 'failed'
            report['error'] = str(error)
            raise
        finally:
            record()
            print('Evidence: ' + str(session), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--validate', action='store_true')
    options = parser.parse_args()
    if options.validate:
        validate()
        print('Preparation checks passed; game was not launched.')
    else:
        try:
            run()
        except Exception as error:
            print('STOPPED: ' + str(error), flush=True)
            raise SystemExit(1)
