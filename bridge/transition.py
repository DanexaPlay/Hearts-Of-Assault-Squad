"""Opt-in request -> fresh paused snapshot -> real mission, without pickers.

The game UI drivers are separate: this module never claims that a snapshot
was taken or that MoW loaded a mission merely because files were generated.
"""
import hashlib,re,shutil,time,uuid
from contextlib import contextmanager
from pathlib import Path
from .core import BridgeError,Ledger,write_json,digest,vanilla_data_compatible
from .hoi import read_campaign,export_combat,vanilla_metadata
from .gem import generate,parse_result,analyze_saved_actors,saved_variable
from .core import read_json,archive_result_evidence

class TransitionBusy(BridgeError):
    """An expected rejected request; the existing transition must keep running."""

def request_fields(line):
    if 'HMB_REQUEST:' not in line: raise BridgeError('Not a tactical request')
    fields={}
    for key,value in re.findall(r'\b(country|seq|province|combat|selection)=([^\s;]+)',line.split('HMB_REQUEST:',1)[1]):
        if key in fields: raise BridgeError('Duplicate request field '+key)
        fields[key]=value
    for key,pattern in [('country',r'[A-Z][A-Z0-9]{2}'),('seq',r'\d+'),('province',r'[1-9]\d*'),('combat',r'\d+:\d+'),('selection',r'native_v1')]:
        if key in fields and not re.fullmatch(pattern,fields[key]): raise BridgeError('Invalid request '+key)
    return fields

def select_requested_combat(campaign,fields):
    if fields.get('selection')=='native_v1' and not all(fields.get(k) for k in ('country','seq','combat','province')):
        raise BridgeError('Missing combat identity from the native button; refusing a fallback battle')
    country=fields.get('country') or campaign.get('player_country')
    if not country: raise BridgeError('Cannot identify requesting country')
    if campaign.get('player_country') and campaign['player_country']!=country:
        raise BridgeError('Snapshot belongs to another player country')
    if 'seq' in fields and campaign.get('countries',{}).get(country,{}).get('hmb_request_seq')!=int(fields['seq']):
        raise BridgeError('Snapshot does not contain this button request')
    combats=[c for c in campaign['combats'] if any(d['country']==country for side in ('attacker','defender') for d in c[side])]
    if 'combat' in fields: combats=[c for c in combats if c['combat_id']==fields['combat']]
    if 'province' in fields: combats=[c for c in combats if c['province']==int(fields['province'])]
    if len(combats)!=1:
        raise BridgeError('Cannot uniquely identify selected battle: '+str(len(combats))+' matches; a combat/province hint is required')
    return combats[0]

def snapshot_signatures(folder):
    folder=Path(folder)
    return {str(p.resolve()):(p.stat().st_mtime_ns,p.stat().st_size) for p in folder.glob('*.hoi4') if p.is_file()}

def install_generated_mod(source,target,session,initialize_bank=False):
    """Replace only our generated files, with per-file backup and rollback."""
    source=Path(source).resolve();target=Path(target).resolve();session=Path(session).resolve()
    if target.name!='HOI4_MoW_Bridge': raise BridgeError('Installation target must be our dedicated mod folder')
    if target==source or target.is_relative_to(source) or source.is_relative_to(target): raise BridgeError('Overlapping installation paths')
    if not (source/'mod.info').is_file(): raise BridgeError('No generated mod metadata')
    missions=list(source.glob('resource/map/single/hmb/*/0.mi'))
    if len(missions)!=1:raise BridgeError('Expected exactly one generated mission')
    mission_rel=missions[0].relative_to(source)
    if not re.fullmatch(r'resource/map/single/hmb/(?:battle(?:_[0-9a-f]{32})?|map_[0-9a-f]{16})/0\.mi',mission_rel.as_posix()):
        raise BridgeError('Invalid generated mission namespace')
    if not mission_rel.parent.name.startswith('map_') and (target/'hmb-map-bank.json').exists():
        raise BridgeError('Map-bank rehearsal is installed. Complete its validation or close MoW and run Restore_Regular_Missions.cmd before using the regular bridge')
    slot=None
    if mission_rel.parent.name.startswith('map_'):
        from .map_bank import validate_slot_package,validate_installed_bank
        slot=validate_slot_package(source,mission_rel)
        if not initialize_bank:
            bank=validate_installed_bank(target)
            registered=next((s for s in bank['slots'] if s['mission_path']==slot['mission_path']),None)
            if not registered or registered['immutable']!=slot['immutable']:
                raise BridgeError('Map is not in the installed bank; close MoW and prepare the bank again')
        for rel,expected in slot['immutable'].items():
            path=target/rel
            if path.exists() and digest(path.read_bytes())!=expected:
                raise BridgeError('Preinstalled map geometry changed; refusing to overwrite a cached slot')
    unique=mission_rel.parent.name!='battle'
    linked=None
    if (source/'hmb-map-link.json').is_file():
        linked=read_json(source/'hmb-map-link.json')
        namespace=linked.get('resource_path','')
        if not isinstance(namespace,str) or not re.fullmatch(r'[0-9a-f]{32}',str(linked.get('battle_id',''))):
            raise BridgeError('Invalid linked map identity')
        native=linked.get('native_archive_source') is True
        valid_namespace=(bool(re.fullmatch(r'(?:multi|single)/[a-z0-9_-]+(?:/[a-z0-9_-]+)*',namespace)) if native else
            bool(re.fullmatch(r'single/hmb/resources_[0-9a-f]{32}',namespace)) and namespace=='single/hmb/resources_'+str(linked.get('battle_id')))
        if not valid_namespace or mission_rel.as_posix()!='resource/map/single/hmb/battle/0.mi':
            raise BridgeError('Invalid linked map namespace')
        wrapper=source/mission_rel.parent/'map'
        raw_wrapper=wrapper.read_bytes()
        if linked.get('binding')=='explicit_land':
            from .map_resources import validate_land_binding
            if not native:raise BridgeError('Explicit land binding requires native resources')
            validate_land_binding(raw_wrapper.decode('utf8'),namespace)
        elif raw_wrapper!=('(include "/map/'+namespace+'/map")\n').encode('utf8'):
            raise BridgeError('Invalid linked map descriptor')
        if digest(raw_wrapper)!=linked.get('map_link_sha256'):
            raise BridgeError('Invalid linked map descriptor')
        if not native and not (source/('resource/map/'+namespace+'/map')).is_file():raise BridgeError('Linked map is missing')
    files=[p for p in source.rglob('*') if p.is_file()]
    for p in files:
        if p.is_symlink(): raise BridgeError('Symlink in generated mod')
        dest=target/p.relative_to(source)
        if not dest.resolve().is_relative_to(target): raise BridgeError('Unsafe destination path')
    unchanged_terrain=[]
    if slot and not initialize_bank:
        # Both installed and generated immutable manifests were checked above.
        # Leave terrain files physically untouched during a warm transfer.
        unchanged_terrain=[p for p in files if p.relative_to(source).as_posix() in slot['immutable']]
        files=[p for p in files if p not in unchanged_terrain]
    backup=session/'install-backup';backup.mkdir(parents=True,exist_ok=True)
    manifest=[];changed=[];geometry_changes=[];difficulty_changes=[];breed_changes=[];entity_changes=[]
    try:
        for p in files:
            rel=p.relative_to(source);dest=target/rel;existed=dest.exists()
            if existed:
                if not dest.is_file(): raise BridgeError('Unexpected directory at generated file destination')
                if re.fullmatch(r'resource/map/single/hmb/(?:battle|resources)_[0-9a-f]{32}/.+',rel.as_posix()) and digest(dest.read_bytes())!=digest(p.read_bytes()):
                    raise BridgeError('A per-battle mission is immutable; generate a new battle UUID')
                old=backup/rel;old.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dest,old)
                if not linked and rel.parent.as_posix()=='resource/map/single/hmb/battle' and re.fullmatch(r'map(?:\.(?:ply|net|grs))?|mtl\d+\.mtl',rel.name) and digest(old.read_bytes())!=digest(p.read_bytes()):
                    geometry_changes.append(rel.as_posix())
            if rel.parent.as_posix()=='resource/set/difficulty' and (not existed or digest(dest.read_bytes())!=digest(p.read_bytes())):
                difficulty_changes.append(rel.as_posix())
            if rel.parent.as_posix()=='resource/set/breed/hmb' and (not existed or digest(dest.read_bytes())!=digest(p.read_bytes())):
                breed_changes.append(rel.as_posix())
            if rel.as_posix().startswith('resource/entity/') and (not existed or digest(dest.read_bytes())!=digest(p.read_bytes())):
                entity_changes.append(rel.as_posix())
            manifest.append({'path':rel.as_posix(),'existed':existed,'new_sha256':digest(p.read_bytes())})
        hidden=[]
        if (target/'resource/map/single/hmb').exists():
            for old in (target/'resource/map/single/hmb').glob('*/interface.set'):
                if old.parent.name==mission_rel.parent.name:continue
                previous_battle=bool(re.fullmatch(r'battle(?:_[0-9a-f]{32})?',old.parent.name))
                previous_bank=not slot and bool(re.fullmatch(r'map_[0-9a-f]{16}',old.parent.name))
                if not (previous_battle or previous_bank):continue
                if not old.resolve().is_relative_to(target):raise BridgeError('Unsafe old mission metadata path')
                rel=old.relative_to(target);saved=backup/rel;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(old,saved)
                entry={'path':rel.as_posix(),'existed':True,'operation':'hide_previous_menu'}
                hidden.append(entry)
            manifest+=hidden
        write_json(session/'install-plan.json',manifest)
        for p,entry in zip(files,manifest):
            dest=target/p.relative_to(source);dest.parent.mkdir(parents=True,exist_ok=True)
            temporary=dest.with_name(dest.name+'.hmb-'+uuid.uuid4().hex+'.tmp')
            try:
                shutil.copy2(p,temporary)
                if digest(temporary.read_bytes())!=entry['new_sha256']: raise BridgeError('Installation copy changed')
                temporary.replace(dest);changed.append(entry)
            finally:
                if temporary.exists(): temporary.unlink()
        for entry in hidden:
            (target/entry['path']).unlink();changed.append(entry)
    except Exception:
        for entry in reversed(changed):
            dest=target/entry['path']
            if entry['existed']: shutil.copy2(backup/entry['path'],dest)
            else: dest.unlink()
        raise
    restart_file=target/'.hmb-engine-restart.json'
    bank_menu_changes=[e['path'] for e in hidden if '/map_' in e['path']]
    if geometry_changes or difficulty_changes or breed_changes or entity_changes or initialize_bank or bank_menu_changes:
        write_json(restart_file,{'reason':'changed_engine_resources','session':str(session),
            'map':geometry_changes,'difficulty':difficulty_changes,'breeds':breed_changes,'entities':entity_changes,'bank_menus':bank_menu_changes})
    report={'target':str(target),'files':len(files),'mission_relative_path':mission_rel.as_posix(),
            'mission_sha256':digest((target/mission_rel).read_bytes()),'game_load_verified':False,
            'unique_mission_resources':unique,'hidden_previous_menus':[e['path'] for e in hidden],
            'map_resource_path':linked['resource_path'] if linked else None,
            'map_slot':slot['mission_path'] if slot else None,
            'requires_engine_restart':restart_file.exists(),'changed_map_resources':geometry_changes,
            'changed_difficulty_resources':difficulty_changes,'changed_breed_resources':breed_changes,'changed_entity_resources':entity_changes,
            'unchanged_terrain_files':len(unchanged_terrain)}
    write_json(session/'installation.json',report);return report

class AutomaticTransfer:
    def __init__(self,cfg,root):
        self.cfg=cfg;self.root=Path(root);self.saves=Path(cfg['hoi4_user'])/'save games'
        self.baseline=snapshot_signatures(self.saves);self.pending=None;self.seen=set();self.stable={};self.result_stable={}
        self.root.mkdir(parents=True,exist_ok=True)
        self.active_file=self.root/'active-transition.json'
        if self.active_file.exists():
            active=read_json(self.active_file);session=Path(active['session']).resolve()
            if not session.is_relative_to(self.root.resolve()): raise BridgeError('Active transition is outside the session root')
            self.pending=read_json(session/'transition.json')
            if Path(self.pending['path']).resolve()!=session: raise BridgeError('Active transition path mismatch')
    def request(self,line):
        fields=request_fields(line)
        key=(fields.get('country'),fields['seq']) if 'seq' in fields else hashlib.sha256(line.encode()).hexdigest()
        if key in self.seen: return None
        if self.pending and not (self.pending['status']=='failed' and not self.pending.get('installation')):
            raise TransitionBusy('A tactical transition is already active; finish and leave its mission before starting another')
        self.seen.add(key)
        path=self.root/uuid.uuid4().hex;path.mkdir(parents=True,exist_ok=False)
        self.pending={'status':'waiting_snapshot','request':fields,'path':str(path.resolve()),'requested_at_ns':time.time_ns(),'line':line}
        self.stable={};self._record();return self.pending
    def _record(self):
        write_json(Path(self.pending['path'])/'transition.json',self.pending)
        write_json(self.active_file,{'session':self.pending['path']})
    def release(self):
        """Called only after the caller verified the old mission was exited."""
        if not self.pending or self.pending['status']!='result_ready': raise BridgeError('A verified final result is required before release')
        self.pending['status']='mission_exited';self._record()
        self.active_file.unlink();self.pending=None
    def collect_final(self):
        if not self.pending or self.pending['status'] not in ('ready','mission_loaded'):return None
        session=Path(self.pending['path']);b=read_json(session/'battle.json');roster=read_json(session/'roster.json')
        progress=Path(self.cfg['mow_progress']);saves=progress.parent/'save'
        for folder in sorted(saves.glob('autosave*'),key=lambda p:p.stat().st_mtime_ns,reverse=True):
            native=folder/'mission.scn';game=folder/'game.scn'
            if not native.is_file() or not game.is_file():continue
            signature=tuple((p.stat().st_mtime_ns,p.stat().st_size) for p in (native,game))
            if signature[0][0]<self.pending['requested_at_ns']:continue
            if self.result_stable.get(str(folder))!=signature:
                self.result_stable[str(folder)]=signature;continue
            raw=native.read_bytes()
            if ('hmb_'+b['id']).encode() not in raw:continue
            try:
                result=parse_result(b,roster,folder,progress)
            except BridgeError as error:
                if signature!=tuple((p.stat().st_mtime_ns,p.stat().st_size) for p in (native,game)):continue
                text=raw.decode('utf-8-sig');finished=False
                try:finished=saved_variable(text,'hmb_finished')==1
                except BridgeError:pass
                if not finished:
                    from .gem import terminal_autosave_winner
                    try:
                        terminal_autosave_winner(b,game.read_text(encoding='utf-8-sig'),progress);finished=True
                    except BridgeError:pass
                if finished:
                    write_json(session/'result-read-error.json',{'battle_id':b['id'],'path':str(native.resolve()),'error':str(error),'signature':signature})
                    raise BridgeError('Finished tactical result could not be verified: '+str(error)) from error
                continue # Initial/nonterminal autosaves are expected while playing.
            if signature!=tuple((p.stat().st_mtime_ns,p.stat().st_size) for p in (native,game)):continue
            result=archive_result_evidence(result,session)
            write_json(session/'result.json',result)
            self.pending.update(status='result_ready',result_file=str(session/'result.json'),result_winner=result['winner'])
            self._record();return result
        return None
    def collect_loaded(self):
        if not self.pending or self.pending['status']!='ready':return None
        session=Path(self.pending['path']);b=read_json(session/'battle.json');roster=read_json(session/'roster.json')
        saves=Path(self.cfg['mow_progress']).parent/'save'
        for folder in sorted(saves.glob('autosave*'),key=lambda p:p.stat().st_mtime_ns,reverse=True):
            native=folder/'mission.scn';game=folder/'game.scn'
            if not native.is_file() or not game.is_file():continue
            signature=tuple((p.stat().st_mtime_ns,p.stat().st_size) for p in (native,game))
            if signature[0][0]<self.pending['requested_at_ns']:continue
            key='initial:'+str(folder)
            if self.result_stable.get(key)!=signature:self.result_stable[key]=signature;continue
            raw=native.read_bytes()
            if ('hmb_'+b['id']).encode() not in raw:continue
            text=raw.decode('utf-8-sig');game_raw=game.read_bytes()
            if saved_variable(text,'hmb_initial_snapshot')!=1 or saved_variable(text,'hmb_finished')!=0:continue
            audit=analyze_saved_actors(roster,text,game_raw.decode('utf-8-sig'))
            if signature!=tuple((p.stat().st_mtime_ns,p.stat().st_size) for p in (native,game)):continue
            evidence={'path':str(native.resolve()),'sha256':digest(raw),'companions':[{'path':str(game.resolve()),'sha256':digest(game_raw)}]}
            archived=archive_result_evidence({'evidence':evidence},session)['evidence']
            report={'battle_id':b['id'],'actors':len(roster),'actor_audit':audit,'evidence':archived,'engine_load_verified':True}
            write_json(session/'loaded-mission.json',report)
            self.pending.update(status='mission_loaded',engine_load_verified=True);self._record();return report
        return None
    def find_fresh_snapshot(self):
        current=snapshot_signatures(self.saves)
        if not self.pending or self.pending['status']!='waiting_snapshot':
            self.baseline=current;return None
        changed=[p for p,stat in current.items() if stat!=self.baseline.get(p) and stat[0]>=self.pending['requested_at_ns']-2_000_000_000]
        if self.pending.get('native_save_name'):
            stem=self.pending['native_save_name']
            changed=[p for p in changed if Path(p).name in (stem+'.hoi4',stem+'_temp.hoi4')]
        if not changed:return None
        candidate=max(changed,key=lambda p:current[p][0]);signature=current[candidate]
        if self.stable.get(candidate)!=signature:
            self.stable[candidate]=signature;return None
        return Path(candidate)
    def prepare(self,snapshot,install=False):
        if not self.pending or self.pending['status']!='waiting_snapshot': raise BridgeError('No pending tactical request')
        started=time.perf_counter();checkpoint=started;timings={}
        session=Path(self.pending['path']);source=Path(snapshot)
        before=(source.stat().st_mtime_ns,source.stat().st_size)
        preserved=session/'hoi4-source.hoi4';shutil.copy2(source,preserved)
        after=(source.stat().st_mtime_ns,source.stat().st_size)
        if before!=after: raise BridgeError('Snapshot is still being written; retry after it is stable')
        self.pending['status']='reading_snapshot';self._record()
        def mark(stage):
            nonlocal checkpoint
            now=time.perf_counter();timings[stage]=round(now-checkpoint,4);checkpoint=now
            write_json(session/'preparation-timing.json',{'stages_seconds':timings,'total_seconds':round(now-started,4),
                'button_to_current_stage_seconds':round((time.time_ns()-self.pending['requested_at_ns'])/1e9,4)})
        mark('preserve_snapshot')
        try:
            campaign=read_campaign(preserved,combat_units_only=True)
            mark('read_campaign')
            selected=self.pending.get('selected_combat')
            if selected and selected['campaign_id']!=campaign['campaign_id']:
                raise BridgeError('Captured combat selection belongs to another campaign')
            if campaign['speed']!='0': raise BridgeError('Snapshot is not paused')
            if not vanilla_data_compatible(campaign.get('mods',[])): raise BridgeError('Unsupported gameplay mods in snapshot')
            combat=select_requested_combat(campaign,self.pending['request'])
            metadata=vanilla_metadata(campaign,combat['province'],self.cfg['hoi4'])
            b=export_combat(campaign,combat['combat_id'],metadata['state'],metadata['terrain'])
            b['metadata_source']=metadata['source']
            b['terrain_context']={k:metadata[k] for k in ('base_terrain','victory_point_value') if k in metadata}
            b['weather']=metadata.get('weather',{'known':False})
            mark('resolve_battle_and_terrain')
            if self.pending.get('native_capture_verified'):
                from .native import NativeHOI
                organization=NativeHOI(self.cfg.get('hoi4_native_port',17389)).organization_snapshot(b,self.pending['native_health']['game_hour'])
                write_json(session/'native-organization.json',organization)
                b.update(organization_snapshot=organization['units'],organization_scaling_required=True)
            mark('native_organization')
            b['transition_note']='Button request matched to real saved combat; automated game capture and mission loading still require a driver'
            report=generate(b,self.cfg,session)
            mark('generate_mission')
            ledger=Ledger(session/'ledger.sqlite');ledger.register(b);ledger.db.close()
            self.pending.update(status='ready',battle_id=b['id'],combat_id=combat['combat_id'],mission=report,preserved_snapshot=str(preserved.resolve()))
            if install:
                target=Path(self.cfg.get('mow_live_mod',str(Path(self.cfg['mow'])/'mods/HOI4_MoW_Bridge')))
                self.pending['installation']=install_generated_mod(session/'mow_mod',target,session)
            mark('register_and_install')
            self._record();return self.pending
        except Exception as error:
            self.pending.update(status='failed',error=str(error));self._record();raise

@contextmanager
def worker_lock(root):
    """Prevent two services from receiving/acting on the same button request."""
    import msvcrt
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    with (root/'worker.lock').open('a+b') as stream:
        if stream.seek(0,2)==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as error:raise BridgeError('Another transition worker is already running') from error
        try:yield
        finally:
            stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)

def watch(cfg,root,install=False,once=False,desktop=False,native=False):
    with worker_lock(root):return _watch(cfg,root,install,once,desktop,native)


def complete_native_return(automatic,cfg):
    """No implicit fallback after a direct mutation could have started."""
    if automatic.pending.get('strategic_result_applied'):
        raise BridgeError('Strategic result already applied; refusing another return')
    if automatic.pending.get('native_return_stage'):
        raise BridgeError('Previous strategic return was started; inspect its report before continuing')
    session=automatic.pending['path'];mode=cfg.get('native_return_mode','prepared_save')
    if mode=='direct':
        from .live import apply_session
        automatic.pending['native_return_stage']='applying_direct';automatic._record()
        returned=apply_session(session)
        verification={'kind':'live_state','report':str(Path(session)/'live-return.json'),'save_or_load_used':False}
    elif mode=='prepared_save':
        from .native_return import prepare as prepare_return,load as load_return
        automatic.pending['native_return_stage']='preparing';automatic._record()
        prepare_return(session)
        automatic.pending['native_return_stage']='loading';automatic._record()
        returned=load_return(session);verification=returned['verification']
    else:raise BridgeError('Unknown native return mode: '+str(mode))
    if returned['stage']!='verified':raise BridgeError('Native strategic return was not verified')
    automatic.pending.update(native_return_stage='verified',strategic_result_applied=True,return_verification=verification)
    automatic._record();return verification


def release_completed(automatic,cfg,allow_menu=False):
    """Release only after a closed process or positively recognized scene exit."""
    if not automatic.pending or automatic.pending['status']!='result_ready' or not automatic.pending.get('strategic_result_applied'):
        raise BridgeError('A verified applied result is required before releasing a tactical session')
    from .launch_native import running
    if not running('mowas_2.exe'):
        proof={'kind':'mow_process_closed','verified_at_ns':time.time_ns()}
    elif allow_menu:
        from .desktop import GameDesktop
        proof=GameDesktop(cfg,Path(__file__).resolve().parents[1]).confirm_mow_menu(restore_focus=True)
    else:return False
    automatic.pending['mission_exit_verification']=proof;automatic._record()
    write_json(Path(automatic.pending['path'])/'mission-exit.json',proof)
    automatic.release();return True

def _watch(cfg,root,install=False,once=False,desktop=False,native=False):
    """Headless service, usable when the desktop GUI runtime is unavailable."""
    from .requests import RequestWatcher
    watcher=RequestWatcher(Path(cfg['hoi4_user'])/'logs/game.log')
    automatic=AutomaticTransfer(cfg,root)
    driver=None;load_started=None
    controller=None
    if native:
        if desktop:raise BridgeError('Choose native or desktop capture, not both')
        from .native import NativeHOI
        controller=NativeHOI(cfg.get('hoi4_native_port',17389))
        controller.health()
        if cfg.get('mow_auto_load') and not install:
            raise BridgeError('Automatic MoW loading requires installation enabled')
    if desktop:
        from .desktop import GameDesktop
        from .core import ROOT
        driver=GameDesktop(cfg,ROOT)
        if not install:raise BridgeError('Desktop transfer requires installation enabled')
    auto_mow=bool(controller and cfg.get('mow_auto_load'))
    recovered=False
    if auto_mow:
        from .mow_launch import recover_acknowledgment
        recovered=recover_acknowledgment(automatic)
    from .status import SilentStatus,TransferStatus
    status=SilentStatus()
    if controller and cfg.get('show_transfer_progress',False):
        status=TransferStatus();status.start_panel()
    if recovered:
        status.update('loaded',session=automatic.pending['path'])
        print('The prepared mission was started manually; native acknowledgment verified. Result monitoring remains active.',flush=True)
    elif automatic.pending and automatic.pending['status']=='ready' and automatic.pending.get('mow_launch',{}).get('stage')=='manual_wait':
        status.update('manual',session=automatic.pending['path'])
    print('Watching new HOI4 opt-in requests. '+('Native capture and automatic MoW loading enabled.' if auto_mow else 'Native background capture enabled; MoW loading remains manual.' if controller else 'Experimental game UI driver enabled.' if driver else 'Game capture/loading remains manual.'),flush=True)
    while True:
        try:
            if controller and automatic.pending and automatic.pending.get('strategic_result_applied') and automatic.pending['status']=='result_ready':
                if release_completed(automatic,cfg):
                    print('Completed result retained; closed MoW session released. Ready for another battle.',flush=True)
            for line in watcher.poll():
                if controller and automatic.pending and automatic.pending['status']=='result_ready' and automatic.pending.get('strategic_result_applied'):
                    try:release_completed(automatic,cfg,allow_menu=auto_mow)
                    except BridgeError as error:
                        print('New battle request rejected; the completed mission must be left first. '+str(error),flush=True)
                        status.update('rejected',session=automatic.pending['path'],error=str(error));continue
                try:request=automatic.request(line)
                except TransitionBusy as error:
                    print('New battle request rejected. The first battle remains active and monitored.',flush=True)
                    status.update('rejected',session=automatic.pending['path'],error=str(error));continue
                if request:
                    print('Request received; waiting for a fresh paused save. Session: '+request['path'],flush=True)
                    status.update('capture',session=request['path'])
                if request and controller:
                    controller.capture(automatic)
                if request and driver:
                    match=re.search(r'\[(\d{4})\.(\d{2})\.(\d{2})\.(\d{2})\]',line)
                    if not match:raise BridgeError('Cannot identify native default save name from request date')
                    stem=request['request']['country']+'_'+'_'.join(match.groups())
                    backup=Path(request['path'])/'before-ui-save';backup.mkdir()
                    for old in automatic.saves.glob(stem+'*.hoi4'):shutil.copy2(old,backup/old.name)
                    driver.save_snapshot()
            snapshot=automatic.find_fresh_snapshot()
            if (driver or controller) and automatic.pending and automatic.pending['status']=='waiting_snapshot' and time.time_ns()-automatic.pending['requested_at_ns']>120_000_000_000:
                raise BridgeError('HOI4 did not produce a fresh save within 120 seconds')
            if snapshot:
                print('Fresh snapshot found; generating tactical mission.',flush=True)
                status.update('generate',session=automatic.pending['path'])
                if controller:
                    state=controller.health();capture=automatic.pending['native_health']
                    if not state['paused'] or state['game_hour']!=capture['game_hour']:raise BridgeError('Campaign changed before mission generation')
                if driver and not driver.mission_menu_ready():raise BridgeError('Leave MoW at the bridge mission menu before a desktop transfer')
                report=automatic.prepare(snapshot,install)
                print('Mission ready: '+report['mission']['path'],flush=True)
                if controller and not auto_mow:status.update('manual',session=automatic.pending['path'])
                if driver:driver.load_mission();load_started=time.monotonic()
                elif once and not auto_mow:return report
            if auto_mow and automatic.pending and automatic.pending['status']=='ready' and not automatic.pending.get('mow_launch'):
                from .mow_launch import start as start_mow
                print('Opening Men of War and selecting the generated battle.',flush=True)
                status.update('open',session=automatic.pending['path'])
                try:
                    launch=start_mow(automatic,cfg,Path(__file__).resolve().parents[1],
                        progress=lambda step:status.update('restart' if step=='restart_for_changed_map' else 'open',session=automatic.pending['path']))
                    status.update('loaded' if launch['game_load_verified'] else 'verify',session=automatic.pending['path'])
                except (OSError,BridgeError) as error:
                    automatic.pending.setdefault('mow_launch',{}).update(stage='manual_wait',error=str(error))
                    automatic._record()
                    from .status import manual_mission_message
                    print('Automatic menu navigation stopped. '+manual_mission_message(automatic.pending['path'])+' '+str(error),flush=True)
                    status.update('manual',session=automatic.pending['path'])
            loaded=automatic.collect_loaded()
            if loaded:
                if automatic.pending.get('mow_launch'):
                    automatic.pending['mow_launch'].update(stage='mission_loaded',game_load_verified=True)
                    automatic._record()
                    write_json(Path(automatic.pending['path'])/'mow-launch.json',automatic.pending['mow_launch'])
                print('Correct tactical mission loaded; roster verified.',flush=True)
                status.update('loaded',session=automatic.pending['path'])
                if once:return automatic.pending
            if auto_mow and automatic.pending and automatic.pending['status']=='ready' and automatic.pending.get('mow_launch'):
                launch=automatic.pending['mow_launch']
                if launch['stage']=='stopped' or (launch['stage']=='waiting_ack' and time.time_ns()-launch['navigation_finished_at_ns']>180_000_000_000):
                    launch['stage']='manual_wait';automatic._record()
                    status.update('manual',session=automatic.pending['path'])
                    from .status import manual_mission_message
                    print(manual_mission_message(automatic.pending['path']),flush=True)
            if driver and load_started and automatic.pending['status']=='ready' and time.monotonic()-load_started>120:
                raise BridgeError('Men of War did not acknowledge this mission within 120 seconds')
            result=automatic.collect_final()
            if result:
                print('Final tactical result verified and archived.',flush=True)
                if not controller:print('Leave the old mission before another transfer.',flush=True)
            if auto_mow and automatic.pending and automatic.pending['status'] in ('ready','mission_loaded'):
                from .mow_launch import engine_failure
                failure=engine_failure(automatic,cfg)
                launch=automatic.pending.get('mow_launch',{})
                if failure and launch.get('engine_error')!=failure:
                    launch['engine_error']=failure;automatic._record()
                    status.update('game_unavailable',session=automatic.pending['path'])
                    print(failure,flush=True)
                elif not failure and launch.pop('engine_error',None):
                    automatic._record()
                    status.update('manual' if automatic.pending['status']=='ready' else 'loaded',session=automatic.pending['path'])
            # Resume an archived result after restart only when no return was
            # ever attempted. A queued/partial mutation must never be retried.
            if controller and automatic.pending and automatic.pending['status']=='result_ready' and not automatic.pending.get('strategic_result_applied'):
                status.update('return',session=automatic.pending['path'])
                complete_native_return(automatic,cfg)
                from .snapshot_cleanup import automatic_cleanup
                automatic_cleanup(cfg,root)
                status.update('done',session=automatic.pending['path'])
                print('Strategic result applied and verified. HOI4 remains paused. Leave the old MoW mission before another transfer.',flush=True)
                if auto_mow:
                    from .desktop import GameDesktop
                    try:GameDesktop(cfg,Path(__file__).resolve().parents[1]).activate('hoi4')
                    except BridgeError as error:print('Result is applied; switch back to HOI4 manually: '+str(error),flush=True)
        except (OSError,BridgeError,ValueError,KeyError) as error:
            print('Transition stopped safely: '+str(error),flush=True)
            status.update('error',session=automatic.pending['path'] if automatic.pending else None,error=str(error))
            if driver or controller:
                if driver:driver.diagnose(error)
                if automatic.pending:
                    automatic.pending['driver_error']=str(error)
                    if automatic.pending['status']=='waiting_snapshot':automatic.pending['status']='failed'
                    automatic._record()
                return {'status':'driver_stopped','error':str(error),'session':automatic.pending}
            if once and automatic.pending and automatic.pending['status']=='failed':return automatic.pending
        time.sleep(1)
