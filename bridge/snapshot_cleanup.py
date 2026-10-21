"""Prune only archived, verified completed bridge captures from HOI4's menu."""
import hashlib,re
from pathlib import Path
from .core import read_json,write_json,ROOT


def file_hash(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def cleanup_plan(cfg,root):
    keep=cfg.get('retained_completed_snapshots',3)
    if type(keep) is not int or keep<1:raise ValueError('Keep at least one completed snapshot')
    saves=(Path(cfg['hoi4_user'])/'save games').resolve();root=Path(root).resolve();completed=[]
    for session in root.iterdir():
        if not session.is_dir() or not session.resolve().is_relative_to(root):continue
        try:record=read_json(session/'transition.json')
        except (OSError,ValueError):continue
        if not isinstance(record,dict):continue
        name=record.get('native_save_name','')
        if not isinstance(name,str) or type(record.get('requested_at_ns',0)) is not int:continue
        if not re.fullmatch(r'HMB_transition_[0-9a-f]{32}',name):continue
        if record.get('strategic_result_applied') is not True or record.get('native_return_stage')!='verified':continue
        backup=session/'hoi4-source.hoi4'
        if not backup.is_file() or not backup.resolve().is_relative_to(session.resolve()):continue
        candidates=[saves/(name+suffix) for suffix in ('.hoi4','_temp.hoi4')]
        present=[p for p in candidates if p.is_file() and p.resolve().parent==saves]
        if present:completed.append((record.get('requested_at_ns',0),backup,present))
    completed.sort(key=lambda item:item[0],reverse=True);rows=[]
    for _,backup,files in completed[keep:]:
        expected=file_hash(backup)
        for source in files:
            stat=source.stat()
            if file_hash(source)!=expected:continue
            rows.append({'path':str(source),'backup':str(backup),'sha256':expected,'size':stat.st_size})
    return {'keep_completed_battles':keep,'files':rows,'bytes':sum(p['size'] for p in rows)}


def cleanup(cfg,root):
    plan=cleanup_plan(cfg,root);removed=[];errors=[]
    saves=(Path(cfg['hoi4_user'])/'save games').resolve()
    for row in plan['files']:
        source=Path(row['path']);backup=Path(row['backup'])
        try:
            # Recheck each exact file immediately before a nonrecursive unlink.
            if source.resolve().parent!=saves or not re.fullmatch(r'HMB_transition_[0-9a-f]{32}(?:_temp)?\.hoi4',source.name):continue
            if file_hash(source)!=row['sha256'] or file_hash(backup)!=row['sha256']:continue
            source.unlink();removed.append(row)
        except OSError as error:errors.append({'path':str(source),'error':str(error)})
    return {**plan,'removed':removed,'errors':errors,'bytes_removed':sum(p['size'] for p in removed)}


def automatic_cleanup(cfg,root):
    # Cleanup is optional housekeeping: an access failure never aborts a battle.
    try:
        report=cleanup(cfg,root)
        write_json(ROOT/'runtime/snapshot-cleanup.json',report)
        if report['removed']:print('Old bridge snapshots cleaned: '+str(len(report['removed']))+'; archived copies retained.',flush=True)
        elif report['errors']:print('Snapshot cleanup could not remove some files; see runtime/snapshot-cleanup.json.',flush=True)
    except (OSError,ValueError) as error:print('Snapshot cleanup skipped: '+str(error),flush=True)
