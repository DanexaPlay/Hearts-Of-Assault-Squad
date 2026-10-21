import hashlib, json, math, re, os, sqlite3, uuid,shutil,copy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
class BridgeError(ValueError): pass
def digest(data): return hashlib.sha256(data).hexdigest()
def read_json(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write_json(path,obj):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf8')
    os.replace(tmp,path)
def config():
    return read_json(ROOT/('config.json' if (ROOT/'config.json').is_file() else 'config.example.json'))

def vanilla_data_compatible(mods):
    # Our GUI-only mod does not replace map, equipment or battalion definitions.
    return isinstance(mods,list) and all(m=='HOI4 Men of War Bridge (experimental)' for m in mods)

def archive_result_evidence(result,session):
    result=copy.deepcopy(result); evidence=result['evidence']
    destination=Path(session)/'evidence'/evidence['sha256']; destination.mkdir(parents=True,exist_ok=True)
    for item in [evidence]+evidence.get('companions',[]):
        source=Path(item['path']); expected=item['sha256']
        if digest(source.read_bytes())!=expected: raise BridgeError('Evidence changed after reading: '+source.name)
        target=destination/source.name
        if source.resolve()!=target.resolve(): shutil.copy2(source,target)
        if digest(target.read_bytes())!=expected: raise BridgeError('Evidence backup failed: '+source.name)
        item['original_path']=item['path']; item['path']=str(target.resolve())
    return result
def tag(s):
    if not isinstance(s,str) or not re.fullmatch(r'[A-Z][A-Z0-9]{2}',s): raise BridgeError('Invalid country tag')
    return s
def integer(v,label,low=1):
    if isinstance(v,bool) or not isinstance(v,int) or v<low: raise BridgeError('Invalid '+label)
    return v
def fraction(v,label):
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1: raise BridgeError('Invalid '+label)
    return v
def validate_battle(b):
    if b.get('schema')!=1: raise BridgeError('Unknown battle schema')
    if not re.fullmatch(r'[a-f0-9]{32}',b.get('id','')): raise BridgeError('Invalid battle ID')
    integer(b['province'],'province'); integer(b['state'],'state')
    if b.get('player_side','attacker') not in ('attacker','defender'): raise BridgeError('Invalid player side')
    for side in ('attacker','defender'):
        s=b[side]; tag(s['country'])
        if not s.get('divisions'): raise BridgeError('No divisions for '+side)
        for d in s['divisions']:
            integer(d['province'],'division province')
            integer(d['manpower'],'manpower')
            fraction(d.get('strength',1),'strength'); fraction(d.get('organization',1),'organization')
    if b['attacker']['country']==b['defender']['country']: raise BridgeError('Sides must be different countries')
    if b.get('war_confirmed') is not True or b.get('paused_confirmed') is not True:
        raise BridgeError('Confirm war and pause before export')
    return b
def resolve_country(country,ideology,cfg=None):
    cfg=cfg or config(); tag(country)
    if country in cfg['country_overrides']: return cfg['country_overrides'][country]
    if country in cfg['native_countries']: return cfg['native_countries'][country]
    choices=cfg['ideology_fallback'].get(ideology)
    if not choices: raise BridgeError('Unknown ideology '+str(ideology)+'; add a mapping in config.json')
    return choices[int(digest(country.encode())[:8],16)%len(choices)]
def choose_map(terrain,river=False,cfg=None,weather=None):
    cfg=cfg or config(); wanted='river' if river else terrain
    actual=cfg['terrain_approximations'].get(wanted,wanted)
    snowy=bool(weather and (weather.get('snow_cover',0)>0 or {'snow','blizzard'}&set(weather.get('conditions',[]))))
    if snowy:
        winter=cfg.get('winter_terrain_approximations',{}).get(actual,actual)
        choices=cfg.get('winter_maps',{}).get(winter)
        if not choices:raise BridgeError('No existing winter map configured for '+str(actual))
        note=f'{wanted} -> {winter} (winter terrain approximation)' if winter!=wanted else None
        return choices[0],note
    choices=cfg['maps'].get(actual)
    if not choices: raise BridgeError('No existing map configured for '+str(wanted))
    return choices[0], None if actual==wanted else f'{wanted} -> {actual} (approximation)'
def make_roster(b,cfg=None):
    cfg=cfg or config(); validate_battle(b); roster=[]
    for side,player in [('attacker',0),('defender',1)]:
        player=0 if side==b.get('player_side','attacker') else 1
        s=b[side]; faction=resolve_country(s['country'],s['ideology'],cfg)
        totals=sum(d['manpower'] for d in s['divisions'])
        if len(s['divisions'])>cfg['max_infantry_per_side']:
            raise BridgeError('Actor budget cannot represent every division on '+side)
        count=max(len(s['divisions']),min(cfg['max_infantry_per_side'],max(1,math.ceil(totals/cfg['soldiers_per_actor']))))
        # Largest remainder distributes the limited actor budget without inventing manpower.
        remaining=count-len(s['divisions'])
        allocations=[1+int(remaining*d['manpower']/totals) for d in s['divisions']]
        order=sorted(range(len(allocations)),key=lambda i: remaining*s['divisions'][i]['manpower']/totals-(allocations[i]-1),reverse=True)
        for i in order[:count-sum(allocations)]: allocations[i]+=1
        for di,(d,n) in enumerate(zip(s['divisions'],allocations)):
            from .readiness import organization_ratio,deployed_count
            n=deployed_count(n,organization_ratio(b,d))
            if not n: continue
            for j in range(n):
                roster.append({'mid':len(roster)+1,'side':side,'player':player,'faction':faction,
                               'division_index':di,'kind':'infantry','breed':f'mp/{faction}/'+('mgun' if j%10==9 else 'rifle'),
                               'represented_manpower':d['manpower']/n})
    return roster

def calculate_result(b,roster,winner,dead_mids,evidence):
    validate_battle(b)
    if winner not in ('attacker','defender'): raise BridgeError('Invalid winner')
    valid={a['mid'] for a in roster}; dead=set(dead_mids)
    if not dead<=valid: raise BridgeError('Unknown actor in result')
    losses={}
    for side in ('attacker','defender'):
        actors=[a for a in roster if a['side']==side]
        per_div=[]
        for di,d in enumerate(b[side]['divisions']):
            own=[a for a in actors if a['division_index']==di]
            represented=min(d['manpower'],sum(a['represented_manpower'] for a in own if a['mid'] in dead))
            per_div.append({'index':di,'manpower_lost':min(d['manpower'],round(represented)),
                            'loss_ratio':fraction(represented/d['manpower'],'loss ratio')})
        losses[side]=per_div
    from .policy import apply_loss_policy
    losses,policy=apply_loss_policy(b,losses,winner)
    equipment_losses={}
    for side in ('attacker','defender'):
        totals={}
        for a in roster:
            if a['side']!=side or a['mid'] not in dead: continue
            for item in a.get('represented_equipment',[]):
                key=(a['division_index'],item['variant_id']); totals[key]=totals.get(key,0)+item['amount']
        equipment_losses[side]=[{'index':di,'variant_id':vid,'amount_lost':amount*policy['max_manpower_loss_ratio']} for (di,vid),amount in totals.items()]
    return {'schema':1,'battle_id':b['id'],'battle_sha256':digest(json.dumps(b,sort_keys=True).encode()),
            'winner':winner,'dead_mids':sorted(dead),'losses':losses,'equipment_losses':equipment_losses,'loss_policy':policy,'evidence':evidence}

def validate_result(b,result):
    validate_battle(b)
    if result['battle_id']!=b['id'] or result['battle_sha256']!=digest(json.dumps(b,sort_keys=True).encode()):
        raise BridgeError('Result belongs to a different snapshot')
    if result.get('evidence',{}).get('kind') not in ('mow_save','mow_progress'): raise BridgeError('Only parsed MoW save/progress evidence can generate apply commands')
    if result.get('winner') not in ('attacker','defender'): raise BridgeError('Unknown winner')
    for side in ('attacker','defender'):
        values=result['losses'][side]
        indices=[x['index'] for x in values]
        if any(isinstance(i,bool) or not isinstance(i,int) for i in indices) or sorted(indices)!=list(range(len(b[side]['divisions']))):
            raise BridgeError('Each participating division must have exactly one loss record')
        for loss in values:
            d=b[side]['divisions'][loss['index']]
            ratio=fraction(loss['loss_ratio'],'loss ratio')
            integer(loss['manpower_lost'],'manpower lost',0)
            if loss['manpower_lost']!=round(d['manpower']*ratio): raise BridgeError('Manpower loss and ratio disagree')
            fraction(loss.get('organization_loss_ratio',ratio),'organization loss')
        seen=set()
        for item in result.get('equipment_losses',{}).get(side,[]):
            idx=item['index']; integer(idx,'equipment division index',0)
            if idx>=len(b[side]['divisions']): raise BridgeError('Unknown equipment division')
            key=(idx,item['variant_id'])
            if key in seen: raise BridgeError('Duplicate equipment loss')
            seen.add(key)
            stock=sum(e['amount'] for e in b[side]['divisions'][idx]['equipment'] if e['variant_id']==item['variant_id'])
            amount=item['amount_lost']
            if isinstance(amount,bool) or not isinstance(amount,(int,float)) or not math.isfinite(amount) or not 0<=amount<=stock:
                raise BridgeError('Equipment loss exceeds exported stock')
    return result

def result_commands(b,result):
    validate_result(b,result)
    # Damage is country + province scoped, NOT an arbitrary division pointer. Refuse
    # ambiguous selections when a snapshot contains additional unselected divisions.
    if b.get('all_divisions_in_locations_confirmed') is not True:
        raise BridgeError('Confirm that every division in the affected locations participates; province damage is not ID-specific')
    flag='hmb_'+b['id']
    pieces=[]
    for side in ('attacker','defender'):
        s=b[side]; grouped={}
        for loss in result['losses'][side]:
            idx=loss['index']; d=s['divisions'][idx]; fraction(loss['loss_ratio'],'loss ratio')
            org=fraction(loss.get('organization_loss_ratio',loss['loss_ratio']),'organization loss')
            key=d['province']; grouped.setdefault(key,[]).append((d['manpower'],loss['loss_ratio'],org))
        for province,values in grouped.items():
            ratio=sum(m*r for m,r,o in values)/sum(m for m,r,o in values)
            org=sum(m*o for m,r,o in values)/sum(m for m,r,o in values)
            if ratio or org: pieces.append(f'damage_units = {{ province = {province} limit = {{ tag = {s["country"]} }} str_damage = {ratio:.8f} org_damage = {org:.8f} ratio = yes army = yes }}')
    if result['winner']=='attacker': pieces.append(f'{b["attacker"]["country"]} = {{ set_province_controller = {b["province"]} }}')
    pieces+=['set_global_flag = '+flag, f'log = "HMB_APPLIED_{b["id"]}"']
    war=f'{b["attacker"]["country"]} = {{ has_war_with = {b["defender"]["country"]} }} {b["defender"]["country"]} = {{ controls_province = {b["province"]} }}'
    return 'eval_effect if = { limit = { NOT = { has_global_flag = '+flag+' } '+war+' } '+' '.join(pieces)+' }'

class Ledger:
    def __init__(self,path):
        self.db=sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS battles(id TEXT PRIMARY KEY, snapshot TEXT NOT NULL, status TEXT NOT NULL, result TEXT)')
        self.db.commit()
    def register(self,b):
        validate_battle(b)
        with self.db: self.db.execute('INSERT INTO battles VALUES(?,?,?,NULL)',(b['id'],json.dumps(b,sort_keys=True),'exported'))
    def stage(self,b,result,current_save=None):
        if b.get('source')=='hoi4_text_save' and b.get('loss_policy') and any(x.get('retreat_required') for values in result['losses'].values() for x in values):
            raise BridgeError('Use a separate prepared save for this result: console damage cannot cancel combat or retreat individual divisions')
        if b.get('source')=='hoi4_text_save':
            if current_save is None: raise BridgeError('Save the current paused HOI4 campaign and provide it for preflight verification')
            from .hoi import verify_snapshot
            preflight=verify_snapshot(b,current_save)
            result={**result,'hoi4_preflight':preflight}
        cmd=result_commands(b,result)
        with self.db:
            row=self.db.execute('SELECT snapshot,status FROM battles WHERE id=?',(b['id'],)).fetchone()
            if not row or row[0]!=json.dumps(b,sort_keys=True): raise BridgeError('Snapshot mismatch')
            if row[1]!='exported': raise BridgeError('Already staged or applied')
            self.db.execute('UPDATE battles SET status=?,result=? WHERE id=?',('staged',json.dumps(result),b['id']))
        return cmd
    def acknowledge(self,battle_id,log_path):
        marker='HMB_APPLIED_'+battle_id
        if marker not in Path(log_path).read_text(encoding='utf8',errors='replace'): raise BridgeError('No application acknowledgment in game.log')
        with self.db:
            cursor=self.db.execute("UPDATE battles SET status='applied' WHERE id=? AND status='staged'",(battle_id,))
            if cursor.rowcount!=1: raise BridgeError('Battle not staged')
    def prepare_save(self,b,result,current_save,output,retreats=None):
        row=self.db.execute('SELECT snapshot,status FROM battles WHERE id=?',(b['id'],)).fetchone()
        if not row or row[0]!=json.dumps(b,sort_keys=True) or row[1]!='exported': raise BridgeError('Snapshot mismatch or already staged/applied')
        from .save_import import prepare_save
        report=prepare_save(b,result,current_save,output,retreats)
        with self.db:
            self.db.execute('UPDATE battles SET status=?,result=? WHERE id=?',('save_prepared',json.dumps(report),b['id']))
        return report
    def acknowledge_save(self,battle_id,path):
        row=self.db.execute('SELECT status,result FROM battles WHERE id=?',(battle_id,)).fetchone()
        if not row or row[0]!='save_prepared': raise BridgeError('No prepared save awaits verification')
        from .save_import import verify_loaded_save
        report=json.loads(row[1]); verified=verify_loaded_save(report,path)
        report['verification']=verified
        with self.db:
            self.db.execute('UPDATE battles SET status=?,result=? WHERE id=?',('applied',json.dumps(report),battle_id))
        return verified
