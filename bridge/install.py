"""One-time connection of the editable mod, without PowerShell or shell input."""
import datetime,re,uuid
from pathlib import Path
from .core import BridgeError,write_json

def connect_mod(cfg,project):
    import _winapi
    project=Path(project).resolve();live=Path(cfg['mow_live_mod']).resolve()
    mods=(Path(cfg['mow'])/'mods').resolve();target=mods/'HOI4_MoW_Bridge'
    if not live.is_relative_to(project) or live.name!='HOI4_MoW_Bridge': raise BridgeError('Editable mod must be inside this project')
    if not (live/'mod.info').is_file(): raise BridgeError('Prepared editable mod is missing')
    if target.parent!=mods or target.name!='HOI4_MoW_Bridge': raise BridgeError('Unexpected installed mod path')
    if target.is_symlink() or target.is_junction():
        if target.resolve()!=live: raise BridgeError('An existing link points elsewhere; nothing was changed')
        report={'connected':True,'already_connected':True,'installed_link':str(target),'editable_mod':str(live)}
        write_json(project/'mod-connection.json',report);return report
    backup=None
    if target.exists():
        metadata=target/'mod.info'
        if not metadata.is_file() or not re.search(r'name\s+"HOI4_MoW_Bridge"',metadata.read_text(encoding='utf8')):
            raise BridgeError('Installed folder is not our dedicated mod; nothing was changed')
        backup=project/'backups'/('mow_installed_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6])
        if not backup.resolve().is_relative_to(project): raise BridgeError('Unsafe backup path')
        if target.drive.lower()!=backup.drive.lower(): raise BridgeError('Automatic backup requires the game and project to be on the same drive')
        backup.parent.mkdir(parents=True,exist_ok=True)
        target.rename(backup)
    try:
        _winapi.CreateJunction(str(live),str(target))
        if not target.is_junction() or target.resolve()!=live: raise BridgeError('Created junction did not match editable mod')
    except Exception:
        if backup and not target.exists():backup.rename(target)
        raise
    report={'connected':True,'installed_link':str(target),'editable_mod':str(live),'backup':str(backup) if backup else None,'game_load_verified':False}
    write_json(project/'mod-connection.json',report);return report
