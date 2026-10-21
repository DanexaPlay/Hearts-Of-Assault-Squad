"""User-run Windows installer. No campaign loading, game launch or save edits."""
import argparse
from contextlib import ExitStack
import ctypes
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import uuid
import Configure

ROOT = Path(__file__).resolve().parent


def steam_libraries():
    roots = [Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Steam']
    if os.name == 'nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
                roots.insert(0, Path(winreg.QueryValueEx(key, 'SteamPath')[0]))
        except OSError:
            pass
    found = []
    for root in list(roots):
        path = root / 'steamapps/libraryfolders.vdf'
        if path.is_file():
            for match in re.finditer(r'"path"\s+"((?:\\.|[^"\\])*)"', path.read_text(encoding='utf-8-sig')):
                roots.append(Path(match[1].replace('\\\\', '\\')))
    for root in roots:
        common = root / 'steamapps/common'
        if common.resolve() not in found:
            found.append(common.resolve())
    return found


def choose_path(title, initial, file=False, non_interactive=False):
    if non_interactive:
        raise ValueError(title + ': укажи путь параметром установщика.')
    import tkinter as tk
    from tkinter import filedialog
    window = tk.Tk(); window.withdraw()
    try:
        if file:
            selected = filedialog.askopenfilename(title=title, initialdir=str(initial),
                                                 filetypes=[('MoW profile', 'game_progress.set')])
        else:
            selected = filedialog.askdirectory(title=title, initialdir=str(initial))
        if not selected:
            raise ValueError('Установка отменена при выборе папки.')
        return Path(selected)
    finally:
        window.destroy()


def discover(args):
    if (ROOT / 'config.json').is_file():
        return json.loads((ROOT / 'config.json').read_text(encoding='utf-8-sig'))
    common = steam_libraries(); docs = Configure.documents()
    def game(explicit, name, exe):
        if explicit:
            return Path(explicit)
        candidates = [base / name for base in common if (base / name / exe).is_file()]
        if len(candidates) == 1:
            return candidates[0]
        return choose_path('Выбери папку ' + name, common[0], non_interactive=args.non_interactive)
    hoi = game(args.hoi4, 'Hearts of Iron IV', 'hoi4.exe')
    mow = game(args.mow, 'Men of War Assault Squad 2', 'mowas_2.exe')
    user = Path(args.hoi4_user) if args.hoi4_user else docs / 'Paradox Interactive/Hearts of Iron IV'
    profiles = docs / 'My Games/men of war - assault squad 2/profiles'
    candidates = list(profiles.glob('*/game_progress.set'))
    progress = Path(args.mow_progress) if args.mow_progress else (
        candidates[0] if len(candidates) == 1 else choose_path(
            'Выбери game_progress.set своего профиля MoW (при первом запуске сначала создай профиль в игре)',
            profiles, file=True, non_interactive=args.non_interactive))
    cfg = json.loads((ROOT / 'config.example.json').read_text(encoding='utf8'))
    cfg.update(hoi4=str(hoi), mow=str(mow), hoi4_user=str(user), mow_progress=str(progress),
               mow_live_mod=str(ROOT / 'runtime/HOI4_MoW_Bridge'))
    return cfg


def validate(cfg):
    for key, exe in [('hoi4', 'hoi4.exe'), ('mow', 'mowas_2.exe')]:
        if not (Path(cfg[key]) / exe).is_file():
            raise ValueError('Не найдена игра: ' + str(Path(cfg[key]) / exe))
    if not Path(cfg['mow_progress']).is_file():
        raise ValueError('Не найден game_progress.set. Запусти MoW один раз и создай профиль.')
    if not (Path(cfg['hoi4_user']) / 'settings.txt').is_file():
        raise ValueError('Не найден settings.txt HOI4. Запусти HOI4 один раз и закрой её.')
    if Path(cfg['mow_live_mod']).resolve() != (ROOT / 'runtime/HOI4_MoW_Bridge').resolve():
        raise ValueError('Конфигурация относится к другой папке проекта; используй отдельный config.json.')
    # Import only the immutable executable signature reader; never call its trial.
    from native_trial.probe import signature, SIGNATURE
    if signature(Path(cfg['hoi4']) / 'hoi4.exe') != SIGNATURE:
        raise ValueError('Неподдерживаемая сборка HOI4. Нужна 1.19.3.0-c01a3d50; файлы игр не изменены.')


def settings_text(raw):
    text = raw.decode('utf-8-sig')
    matches = list(re.finditer(r'(?m)^[ \t]*save_as_binary[ \t]*=[ \t]*(?:yes|no)[ \t]*(?=\r?$)', text))
    keys = re.findall(r'(?m)^[ \t]*save_as_binary[ \t]*=', text)
    if len(keys) > 1 or (keys and not matches):
        raise ValueError('Неоднозначный save_as_binary в settings.txt; файл не изменён.')
    if matches:
        match = matches[0]; text = text[:match.start()] + 'save_as_binary=no' + text[match.end():]
    else:
        text = text.rstrip('\r\n') + '\nsave_as_binary=no\n'
    return text.encode('utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'utf8')


def run_logged(command, env=None):
    with subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding='utf8', errors='replace') as process:
        for line in process.stdout:
            print(line, end='', flush=True)
        code = process.wait()
    if code:
        raise subprocess.CalledProcessError(code, command)


def backed_write(path, data, backup, undo):
    """Back up bytes before an atomic replacement, with a race-safe rollback."""
    path = Path(path); old = path.read_bytes() if path.exists() else None
    if old == data:
        return
    if old is not None:
        backup.parent.mkdir(parents=True, exist_ok=True); backup.write_bytes(old)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.hmb-' + uuid.uuid4().hex)
    temporary.write_bytes(data)
    if (path.read_bytes() if path.exists() else None) != old:
        temporary.unlink(); raise ValueError('Файл изменился во время установки: ' + str(path))
    temporary.replace(path)
    def restore():
        if not path.exists() or path.read_bytes() != data:
            raise ValueError('Автоматический откат не может заменить изменённый файл: ' + str(path))
        if old is None:
            path.unlink()
        else:
            path.write_bytes(old)
    undo.callback(restore)


def existing_installation(cfg):
    target = Path(cfg['mow']) / 'mods/HOI4_MoW_Bridge'
    live = Path(cfg['mow_live_mod']).resolve()
    other_link = (target.is_junction() or target.is_symlink()) and target.resolve() != live
    if (other_link or (target.exists() and not target.is_junction() and not target.is_symlink())):
        metadata = target / 'mod.info'
        if not metadata.is_file() or not re.search(r'name\s+"HOI4_MoW_Bridge"', metadata.read_text(encoding='utf-8-sig')):
            raise ValueError('Существующая папка HOI4_MoW_Bridge не распознана как наш мод; она не изменена.')
    descriptor = Path(cfg['hoi4_user']) / 'mod/hoi4_mow_bridge.mod'
    old_descriptor = descriptor.read_text(encoding='utf-8-sig') if descriptor.exists() else ''
    if old_descriptor and 'HOI4 Men of War Bridge' not in old_descriptor:
        raise ValueError('Файл hoi4_mow_bridge.mod принадлежит другому моду; установка остановлена.')
    descriptor_elsewhere = old_descriptor and ('path=' + json.dumps((ROOT / 'hoi4_mod').as_posix())) not in old_descriptor
    return target, bool(other_link), bool(descriptor_elsewhere)


def integrate(cfg, backup, replace_existing=False):
    from bridge.install import connect_mod
    target, other_link, other_descriptor = existing_installation(cfg)
    if (other_link or other_descriptor) and not replace_existing:
        raise ValueError('Найдена другая установка моста; требуется подтверждение замены.')
    with ExitStack() as undo:
        settings = Path(cfg['hoi4_user']) / 'settings.txt'
        backed_write(settings, settings_text(settings.read_bytes()), backup / 'settings.txt', undo)
        descriptor = Path(cfg['hoi4_user']) / 'mod/hoi4_mow_bridge.mod'
        text = (ROOT / 'hoi4_mod/descriptor.mod').read_text(encoding='utf8')
        text += '\npath=' + json.dumps((ROOT / 'hoi4_mod').as_posix()) + '\n'
        backed_write(descriptor, text.encode('utf8'), backup / 'hoi4_mow_bridge.mod', undo)
        if other_link:
            if not target.is_junction():
                raise ValueError('Обнаружена другая символическая ссылка; переключи её вручную.')
            import _winapi
            previous = target.resolve()
            backup.mkdir(parents=True, exist_ok=True)
            (backup / 'previous-mow-link.json').write_text(json.dumps({'target':str(target),'previous':str(previous)}, indent=2), encoding='utf8')
            # rmdir removes only the junction, never recursively touches its target.
            target.rmdir()
            undo.callback(lambda: _winapi.CreateJunction(str(previous), str(target)))
        report = connect_mod(cfg, ROOT)
        undo.pop_all()  # Both game integration steps succeeded.
    return report


def native_ready():
    manifest = json.loads((ROOT / 'native_trial/manifest.json').read_text(encoding='utf8'))
    return all((ROOT / 'native_trial' / name).is_file() and
               hashlib.sha256((ROOT / 'native_trial' / name).read_bytes()).hexdigest() == value
               for name, value in manifest['binaries'].items())


def install_worker(cfg, args):
    from bridge.core import write_json
    from bridge.launch_native import running
    from bridge.map_bank import prepare_bank, supported_maps, validate_installed_bank
    from bridge.transition import worker_lock
    with worker_lock(ROOT / 'sessions/automatic'):
        if any(running(exe) for exe in ('hoi4.exe', 'mowas_2.exe', 'mowas_2_ed.exe')):
            raise ValueError('Закрой HOI4, MoW и редактор, затем запусти Install.cmd снова.')
        active = ROOT / 'sessions/automatic/active-transition.json'
        if active.exists():
            raise ValueError('Есть незавершённый бой. Сначала заверши или отмени его.')
        print('[4/6] Проверяем и скачиваем нативный компонент…', flush=True)
        if not native_ready():
            Configure.download_native()
        print('[5/6] Подготавливаем штатные карты MoW. Это может занять несколько минут…', flush=True)
        target = Path(cfg['mow_live_mod'])
        if (target / 'hmb-map-bank.json').exists():
            validate_installed_bank(target)
        else:
            maps, skipped = supported_maps(cfg)
            if len(maps) != 7:
                raise ValueError('Ожидалось семь проверенных карт MoW; проверь версию и целостность игры.')
            settings = {**cfg, 'maps':{'catalogue':maps}, 'winter_maps':{}}
            fixture = json.loads((ROOT / 'examples/battle.example.json').read_text(encoding='utf8'))
            prepare_bank(settings, fixture, ROOT / 'runtime/install-map-bank', install=True)
        print('[6/6] Подключаем моды и текстовые снимки HOI4…', flush=True)
        backup = ROOT / 'backups' / ('installer_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6])
        report = integrate(cfg, backup, args.replace_existing)
        write_json(ROOT / 'runtime/installation-complete.json', {'status':'installed','game_load_verified':False,'backup':str(backup),'connection':report})
    print('\nУСТАНОВКА ЗАВЕРШЕНА.\n1. В лаунчере HOI4 включи HOI4 Men of War Bridge (experimental).\n2. В MoW включи HOI4_MoW_Bridge и один раз перезапусти игру.\n3. Запускай Start_Native_Bridge.cmd. Папку установки больше не перемещай.\nСохранения кампаний не изменялись.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('hoi4','mow','hoi4-user','mow-progress'):
        parser.add_argument('--' + name)
    for name in ('dry-run','non-interactive','replace-existing','worker','elevated'):
        parser.add_argument('--' + name, action='store_true')
    args = parser.parse_args()
    if os.name != 'nt' or sys.version_info < (3,12) or struct.calcsize('P') != 8:
        raise ValueError('Нужны Windows x64 и Python 3.12+ x64.')
    print('[1/6] Определяем папки игр и профиль…', flush=True)
    cfg = discover(args); validate(cfg)
    from bridge.launch_native import running
    games = [exe for exe in ('hoi4.exe','mowas_2.exe','mowas_2_ed.exe') if running(exe)]
    if args.dry_run:
        print(json.dumps({'status':'dry_run','paths':cfg,'running_games':games,'changes_made':False},ensure_ascii=False,indent=2))
        return
    if games:
        raise ValueError('Закрой игры и редактор перед установкой: ' + ', '.join(games))
    _, other_link, other_descriptor = existing_installation(cfg)
    if (other_link or other_descriptor) and not args.replace_existing:
        if args.non_interactive:
            raise ValueError('Найдена прежняя установка. Для её переключения требуется --replace-existing.')
        answer = input('Найдена прежняя установка моста. Переключить на эту папку с резервной копией? [y/N]: ')
        if answer.strip().lower() not in ('y','yes','д','да'):
            raise ValueError('Установка отменена. Прежний мост не изменён.')
        args.replace_existing = True
    if args.worker:
        install_worker(cfg, args); return
    print('[2/6] Сохраняем локальную конфигурацию…', flush=True)
    if not (ROOT / 'config.json').exists():
        with (ROOT / 'config.json').open('x', encoding='utf8') as stream:
            json.dump(cfg, stream, ensure_ascii=False, indent=2)
    print('[3/6] Готовим изолированный Python и зависимости…', flush=True)
    python = ROOT / '.venv/Scripts/python.exe'
    if not python.is_file():
        run_logged([sys.executable, '-m', 'venv', str(ROOT / '.venv')])
    env = {**os.environ, 'PYTHONUTF8':'1'}
    run_logged([str(python), '-m', 'pip', 'install', '--disable-pip-version-check', '-r', str(ROOT / 'requirements.txt')], env=env)
    command = [str(python), str(ROOT / 'installer.py'), '--worker', '--non-interactive']
    if args.replace_existing:
        command.append('--replace-existing')
    if args.elevated:
        command.append('--elevated')
    run_logged(command, env=env)


class Tee:
    def __init__(self, output, log):
        self.output, self.log = output, log
    def write(self, value):
        self.output.write(value); self.log.write(value); return len(value)
    def flush(self):
        self.output.flush(); self.log.flush()


if __name__ == '__main__':
    if '--dry-run' not in sys.argv and '--worker' not in sys.argv:
        (ROOT / 'runtime').mkdir(exist_ok=True)
        log = (ROOT / 'runtime/installer.log').open('a', encoding='utf8', buffering=1)
        sys.stdout = Tee(sys.stdout, log); sys.stderr = Tee(sys.stderr, log)
    try:
        main()
    except PermissionError as error:
        print('Windows запретила запись: ' + str(error), file=sys.stderr)
        print('Перезапусти Install.cmd через «Запуск от имени администратора». Резервные копии — в backups.', file=sys.stderr)
        raise SystemExit(1)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print('Установка остановлена: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
