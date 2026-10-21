"""Reversible, single-field native probe. No save/load command is used."""
import json
import pathlib
import sys
import time
from datetime import datetime
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from bridge.native import NativeHOI

LOCATE = r'''
assert(HMB_DIRECT_PROBE == nil, "Previous direct probe requires inspection")
local b=hoi4.base(); local r=hoi4.read_u64; local u=hoi4.read_u32
local gs=r(b+0x332F260); assert(gs and gs>65536)
local data=r(gs+0x310); local count=u(gs+0x31C)
assert(data and count and count>0 and count<4096)
local found=nil
for c=0,count-1 do
 local country=r(data+8*c)
 if country and country>65536 then
  local units=r(country+656); local n=u(country+668)
  assert(n and n<100000)
  if units and units>65536 then
   for i=0,n-1 do
    local d=r(units+8*i)
    if d and d>65536 and r(d)==b+0x295a2b0 and r(d+16)==b+0x295a490
      and u(d+24)==51 and u(d+28)==1 then
     local p=r(d+496);local t=r(d+952)
     assert(p and t and u(p+164)==9039 and u(t+12)==3, "Unexpected division identity")
     assert(not found,"Ambiguous division")
     found=d
    end
   end
  end
 end
end
assert(found,"Division not found")
local org=r(found+1064);assert(org==431849,"Organization changed since verified return")
HMB_DIRECT_PROBE={base=b,gs=gs,addr=found,original=org,changed=org-100000}
return string.format("%d|%d|%d",found,org,org-100000)
'''

GUARD = r'''
local p=assert(HMB_DIRECT_PROBE,"Probe backup missing")
assert(hoi4.base()==p.base and hoi4.read_u64(p.base+0x332F260)==p.gs,"Campaign changed")
assert(hoi4.read_u64(p.addr)==p.base+0x295a2b0
 and hoi4.read_u64(p.addr+16)==p.base+0x295a490
 and hoi4.read_u32(p.addr+24)==51 and hoi4.read_u32(p.addr+28)==1,"Division changed")
'''


def main():
    client=NativeHOI();state=client.health()
    if not state['paused'] or state['date']!='1936.1.1.16':
        raise RuntimeError('Expected paused test campaign; no mutation performed')
    folder=pathlib.Path(__file__).parent/'evidence'/('direct_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
    folder.mkdir(parents=True)
    report={'stage':'locating','health_before':state,'save_or_load_used':False}
    def record():
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    record()
    report['located']=client.request('/lua',LOCATE)
    report['stage']='located';record()
    try:
        report['stage']='write_requested';record()
        report['write']=client.request('/lua',GUARD+r'''
assert(hoi4.read_u64(p.addr+1064)==p.original,"Original field changed")
assert(hoi4.write_u64(p.addr+1064,p.changed),"Write rejected")
return tostring(hoi4.read_u64(p.addr+1064))
''')
        time.sleep(3)
        report['persistent_value']=client.request('/lua',GUARD+r'''
assert(hoi4.read_u64(p.addr+1064)==p.changed,"Engine replaced probe value")
return tostring(hoi4.read_u64(p.addr+1064))
''')
    finally:
        report['restore']=client.request('/lua',GUARD+r'''
local current=hoi4.read_u64(p.addr+1064)
assert(current==p.original or current==p.changed,"Unexpected field state; manual inspection required")
assert(hoi4.write_u64(p.addr+1064,p.original),"Restoration rejected")
assert(hoi4.read_u64(p.addr+1064)==p.original,"Restoration failed")
return tostring(hoi4.read_u64(p.addr+1064))
''')
        report['stage']='restored';record()
    report['health_after']=client.health()
    if not report['health_after']['paused'] or report['health_after']['game_hour']!=state['game_hour']:
        raise RuntimeError('Campaign time changed during probe')
    report['stage']='passed';record()
    print(json.dumps(report,ensure_ascii=False,indent=2))
    print('Evidence:',folder)


if __name__=='__main__':main()
