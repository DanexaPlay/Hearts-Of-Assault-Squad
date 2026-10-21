"""Prepare two fronts in the known separate test campaign, with a full backup."""
import shutil,time,uuid
from pathlib import Path
from bridge.core import ROOT,BridgeError,config,write_json
from bridge.live import LiveHOI,lua


def main():
    client=LiveHOI();health=client.client.health();cfg=config()
    plan={'units':{k:True for k in ('1:51','2:51','373:51','374:51')},'provinces':{'9039':True,'74':True,'142':True,'9203':True}}
    before=client.inspect(plan)
    if not health['paused'] or before['campaign_id']!='1da5640a-7feb-4813-b135-9d82a19c6d25' or before['combats']:
        raise BridgeError('Expected the known paused test campaign without active combats')
    expected={'1:51':'GER','2:51':'GER','373:51':'SOV','374:51':'SOV'}
    for k,c in expected.items():
        if k not in before['units'] or before['units'][k]['country']!=c or before['units'][k]['combat_count']:
            raise BridgeError('Unexpected selection fixture division')
    root=ROOT/'native_trial/evidence'/('selection_setup_'+uuid.uuid4().hex);root.mkdir(parents=True)
    report={'before':before,'health':health,'commands':[]};write_json(root/'setup.json',report)
    def save(stem):
        client.client.request('/console','savegame '+stem,timeout=65)
        end=time.monotonic()+60;last=None
        while time.monotonic()<end:
            paths=list((Path(cfg['hoi4_user'])/'save games').glob(stem+'*.hoi4'))
            if len(paths)==1:
                p=paths[0];sig=(p.stat().st_size,p.stat().st_mtime_ns)
                if last==sig and sig[0]>100000:
                    shutil.copy2(p,root/p.name);return str(p)
                last=sig
            time.sleep(.5)
        raise BridgeError('Selection fixture save did not stabilize')
    report['backup']=save('HMB_before_selection_'+root.name[-12:]);write_json(root/'setup.json',report)
    for command in ('eval_effect SOV = { set_province_controller = 142 set_province_controller = 9203 }','moveunit 1 9039','moveunit 2 74','moveunit 373 142','moveunit 374 9203'):
        item={'command':command,'stage':'intent'};report['commands'].append(item);write_json(root/'setup.json',report)
        result=client.client.request('/console',command)
        if 'error' in result.get('result','').lower():raise BridgeError('Fixture console command failed; inspect setup report and backup')
        item.update(stage='returned',result=result);write_json(root/'setup.json',report)
    code='local s=HMB_LIVE.inspect('+lua(plan)+'); assert(s.campaign_id=='+lua(before['campaign_id'])+'); for k,v in pairs(s.units) do assert(v.combat_count==0); assert(hoi4.call_u64(hoi4.base()+0xC8F170,v.addr,4000000)~=nil) end; return "fixture organisation set"'
    report['organisation']=client.client.request('/lua',code)
    after=client.inspect(plan)
    for k,p in {'1:51':9039,'2:51':74,'373:51':142,'374:51':9203}.items():
        if after['units'][k]['province']!=p or abs(after['units'][k]['org']-4000000)>1:raise BridgeError('Fixture position or organisation mismatch')
    report['after']=after;report['fixture_save']=save('HMB_selection_setup_'+root.name[-12:]);write_json(root/'setup.json',report)
    print({'fixture_save':report['fixture_save'],'backup':report['backup'],'report':str(root/'setup.json')})

if __name__=='__main__':main()
