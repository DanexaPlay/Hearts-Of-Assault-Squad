"""Portable, explicit setup. Never starts either game or changes a campaign."""
import argparse
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
NATIVE_URL = 'https://github.com/ari-20/hoi4_lua/releases/download/v0.5/hoi4_lua-0.5-win-x64.zip'


def documents():
    if os.name == 'nt':
        value = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, value) == 0:
            return Path(value.value)
    return Path.home() / 'Documents'


def configuration(args):
    cfg = json.loads((ROOT / 'config.example.json').read_text(encoding='utf8'))
    common = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Steam/steamapps/common'
    docs = documents()
    cfg.update(
        hoi4=str(Path(args.hoi4) if args.hoi4 else common / 'Hearts of Iron IV'),
        mow=str(Path(args.mow) if args.mow else common / 'Men of War Assault Squad 2'),
        hoi4_user=str(Path(args.hoi4_user) if args.hoi4_user else docs / 'Paradox Interactive/Hearts of Iron IV'),
        mow_live_mod=str(ROOT / 'runtime/HOI4_MoW_Bridge'))
    if args.mow_progress:
        cfg['mow_progress'] = str(Path(args.mow_progress))
    else:
        candidates = list((docs / 'My Games/men of war - assault squad 2/profiles').glob('*/game_progress.set'))
        if len(candidates) != 1:
            raise ValueError('Use --mow-progress with the exact game_progress.set of your MoW profile.')
        cfg['mow_progress'] = str(candidates[0])
    for key, filename in [('hoi4', 'hoi4.exe'), ('mow', 'mowas_2.exe')]:
        if not (Path(cfg[key]) / filename).is_file():
            raise ValueError('Game not found; specify --' + key + ' with its installation folder.')
    if not Path(cfg['mow_progress']).is_file():
        raise ValueError('MoW progress file does not exist; start the game once and check its profile.')
    output = ROOT / 'config.json'
    # A fresh config never silently replaces an existing installation.
    with output.open('x', encoding='utf8') as stream:
        json.dump(cfg, stream, ensure_ascii=False, indent=2)
    return cfg


def download_native():
    manifest = json.loads((ROOT / 'native_trial/manifest.json').read_text(encoding='utf8'))
    request = urllib.request.Request(NATIVE_URL, headers={'User-Agent': 'Hearts-Of-Assault-Squad'})
    with urllib.request.urlopen(request, timeout=90) as response:
        archive = response.read(64 * 1024 * 1024 + 1)
    if len(archive) > 64 * 1024 * 1024 or hashlib.sha256(archive).hexdigest() != manifest['archive_sha256']:
        raise ValueError('Native archive hash mismatch. Nothing was installed.')
    payload = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        for name, expected in manifest['binaries'].items():
            matches = [n for n in source.namelist() if n.replace('\\', '/').rsplit('/', 1)[-1] == name]
            if len(matches) != 1:
                raise ValueError('Ambiguous native archive entry: ' + name)
            data = source.read(matches[0])
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('Native binary hash mismatch: ' + name)
            payload[name] = data
    for name, data in payload.items():
        target = ROOT / 'native_trial' / name
        if target.exists() and target.read_bytes() != data:
            raise ValueError('A different native binary exists; preserve/remove it manually: ' + name)
    for name, data in payload.items():
        (ROOT / 'native_trial' / name).write_bytes(data)
    print('Verified upstream native runtime installed; no game was launched.')


def register_hoi(cfg):
    mods = Path(cfg['hoi4_user']) / 'mod'
    mods.mkdir(parents=True, exist_ok=True)
    target = mods / 'hoi4_mow_bridge.mod'
    text = (ROOT / 'hoi4_mod/descriptor.mod').read_text(encoding='utf8')
    text += '\npath=' + json.dumps((ROOT / 'hoi4_mod').as_posix(), ensure_ascii=False) + '\n'
    if target.exists() and target.read_text(encoding='utf8') != text:
        raise ValueError('An existing bridge descriptor differs. Back it up before replacing: ' + str(target))
    target.write_text(text, encoding='utf8')
    print('HOI4 mod registered. Enable it in the launcher; other gameplay mods are unsupported.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hoi4')
    parser.add_argument('--mow')
    parser.add_argument('--hoi4-user')
    parser.add_argument('--mow-progress')
    parser.add_argument('--download-native', action='store_true')
    parser.add_argument('--register-hoi', action='store_true')
    args = parser.parse_args()
    existing = ROOT / 'config.json'
    if existing.is_file():
        if any((args.hoi4, args.mow, args.hoi4_user, args.mow_progress)):
            raise ValueError('config.json already exists; edit it explicitly instead of overwriting it.')
        cfg = json.loads(existing.read_text(encoding='utf-8-sig'))
    else:
        cfg = configuration(args)
    if args.download_native:
        download_native()
    if args.register_hoi:
        register_hoi(cfg)
    print('Configuration ready. See README.md for map-bank setup and first launch.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        raise SystemExit('Setup stopped: ' + str(error))
