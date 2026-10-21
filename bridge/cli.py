import argparse,json,uuid,shutil
from pathlib import Path
from .core import config,read_json,write_json,validate_battle,Ledger,ROOT,BridgeError,archive_result_evidence
from .gem import generate,parse_result
from .clausewitz import read_save

def main():
    p=argparse.ArgumentParser(description='HOI4 x MoW experimental bridge')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor')
    s=sub.add_parser('generate'); s.add_argument('battle'); s.add_argument('--out',required=True)
    s=sub.add_parser('result'); s.add_argument('session'); s.add_argument('mow_save')
    s=sub.add_parser('stage'); s.add_argument('session'); s.add_argument('--current-save')
    s=sub.add_parser('ack'); s.add_argument('session'); s.add_argument('hoi4_log')
    s=sub.add_parser('prepare-save'); s.add_argument('session'); s.add_argument('--current-save',required=True); s.add_argument('--out',required=True); s.add_argument('--retreats',help='JSON mapping defending division IDs to friendly neighboring provinces')
    s=sub.add_parser('ack-save'); s.add_argument('session'); s.add_argument('fresh_save')
    s=sub.add_parser('inspect-save'); s.add_argument('save')
    s=sub.add_parser('list-battles'); s.add_argument('save'); s.add_argument('--out')
    s=sub.add_parser('export-battle'); s.add_argument('save'); s.add_argument('combat_id'); s.add_argument('--state',type=int,required=True); s.add_argument('--terrain',required=True); s.add_argument('--river',action='store_true'); s.add_argument('--out',required=True)
    s=sub.add_parser('gui')
    s=sub.add_parser('watch');s.add_argument('--root',default=str(ROOT/'sessions/automatic'));s.add_argument('--install',action='store_true');s.add_argument('--once',action='store_true');s.add_argument('--desktop',action='store_true');s.add_argument('--native',action='store_true')
    a=p.parse_args(); cfg=config()
    if a.command=='gui':
        from .gui import run
        return run()
    if a.command=='watch':
        from .transition import watch
        return watch(cfg,a.root,a.install,a.once,a.desktop,a.native)
    if a.command=='doctor':
        report={k:{'path':cfg[k],'installed':(Path(cfg[k])/exe).is_file()} for k,exe in [('hoi4','hoi4.exe'),('mow','mowas_2.exe')]}
        report['limitations']=['No binary save decoder',
            'Native HOI4 capture uses a background text snapshot; direct strategic return avoids save/load',
            'Multiple simultaneous battles require explicit identification; ambiguous requests are rejected',
            'Battalions, equipment mix, crews, capture scoring, HUD, preparation and timeout verified in regular MoW; map classifications are curated',
            'Men of War mission opening remains manual in native mode; opt-in only',
            'Native mode requires hoi4_lua v0.5 and HOI4 1.19.3.0-c01a3d50']
        print(json.dumps(report,ensure_ascii=False,indent=2)); return
    if a.command=='inspect-save':
        _,tree=read_save(a.save)
        print(json.dumps({'top_level':[n.key for n in tree.children if n.key],
              'divisions':sum(1 for _ in tree.walk('division'))},ensure_ascii=False,indent=2)); return
    if a.command in ('list-battles','export-battle'):
        from .hoi import read_campaign,export_combat
        campaign=read_campaign(a.save)
        if a.command=='list-battles':
            report={k:campaign[k] for k in ('source_path','source_sha256','date','campaign_id','speed','combats')}
            if a.out: write_json(a.out,report)
            summary={'date':campaign['date'],'campaign_id':campaign['campaign_id'],'combats':[
                {'id':c['combat_id'],'province':c['province'],
                 'attacker':{'countries':sorted({d['country'] for d in c['attacker']}),'divisions':len(c['attacker']),'manpower':sum(d['manpower'] for d in c['attacker'])},
                 'defender':{'countries':sorted({d['country'] for d in c['defender']}),'divisions':len(c['defender']),'manpower':sum(d['manpower'] for d in c['defender'])}}
                for c in campaign['combats']]}
            print(json.dumps(summary,ensure_ascii=False,indent=2))
        else:
            b=export_combat(campaign,a.combat_id,a.state,a.terrain,a.river)
            validate_battle(b); write_json(a.out,b); print('Exported real combat '+a.combat_id+' to '+a.out)
        return
    session=Path(a.out if a.command=='generate' else a.session).resolve()
    session.mkdir(parents=True,exist_ok=True)
    if a.command=='generate':
        b=read_json(a.battle); validate_battle(b)
        if (session/'ledger.sqlite').exists(): raise BridgeError('Session already exists; use a new folder')
        report=generate(b,cfg,session)
        ledger=Ledger(session/'ledger.sqlite'); ledger.register(b)
        print(json.dumps(report,ensure_ascii=False,indent=2)); return
    b=read_json(session/'battle.json'); ledger=Ledger(session/'ledger.sqlite')
    if a.command=='prepare-save':
        retreats=read_json(a.retreats) if a.retreats else None
        report=ledger.prepare_save(b,read_json(session/'result.json'),a.current_save,a.out,retreats)
        write_json(session/'prepared_save.json',report)
        with ledger.db: ledger.db.execute('UPDATE battles SET status=?,result=? WHERE id=?',('save_prepared',json.dumps(report),b['id']))
        print(json.dumps(report,ensure_ascii=False,indent=2))
        print('Separate save prepared. Load it in HOI4; engine acceptance has not yet been verified.')
    elif a.command=='ack-save':
        report=ledger.acknowledge_save(b['id'],a.fresh_save)
        write_json(session/'loaded_save_verification.json',report)
        print(json.dumps(report,ensure_ascii=False,indent=2))
    elif a.command=='result':
        result=parse_result(b,read_json(session/'roster.json'),a.mow_save)
        result=archive_result_evidence(result,session)
        write_json(session/'result.json',result)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    elif a.command=='stage':
        cmd=ledger.stage(b,read_json(session/'result.json'),a.current_save)
        from .commands import write_apply_files
        batch,run_command=write_apply_files(session,b,cmd)
        print('Prepared batch: '+str(batch))
        print('Copy this file into the HOI4 installation folder; then use the short console command: '+run_command)
        print('Relative batch loading verified in HOI4 1.19.3. Do not paste the long effect into the console input.')
    elif a.command=='ack':
        ledger.acknowledge(b['id'],a.hoi4_log); print('Application acknowledgment found')

if __name__=='__main__':
    try: main()
    except (ValueError,KeyError,OSError) as e: raise SystemExit('Bridge error: '+str(e))
