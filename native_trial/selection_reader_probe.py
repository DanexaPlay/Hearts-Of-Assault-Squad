"""Exercise the Lua selection reader in isolated fake memory via the runtime.

The fake hoi4 API never reads or changes the game. This checks Lua behavior,
not the correctness of the real game's selected-view pointer layout.
"""
import json
from bridge.core import ROOT,write_json
from bridge.native import NativeHOI

HARNESS=r'''
local mem,str={},{};local base=0x140000000
local g,idler,handler,view=0x30000000,0x20000000,0x20010000,0x20020000
local pool,c1,c2=0x30010000,0x40000000,0x40010000
local ca,cc,vars,vd=0x50000000,0x50010000,0x50020000,0x50030000
local tags=0x60000000;local pauses=0;local callbacks={}
local function put(p,v) mem[p]=v end
local function read(p) assert(mem[p]~=nil,'Unexpected fake-memory read '..string.format('%x',p));return mem[p] end
put(base+0x332F260,g);put(base+0x332F698,idler);put(idler,base+0x2968ff0)
put(idler+1720,handler);put(handler+504,view);put(view,base+0x29de3b0)
put(g+628,2);put(g+616,pool);put(pool,c1);put(pool+8,c2)
put(g+700,1000);put(g+1128,123);str[g+1832]='fixture-campaign'
put(g+868,3);put(g+856,tags);str[tags+32]='GER';str[tags+64]='SOV'
put(g+796,3);put(g+784,ca);put(ca+8,cc);put(cc+8,1);put(cc+536,vars)
put(vars+32,1);put(vars+36,0);put(vars+40,0);put(vars+24,vd)
put(vd+4,1);str[vd+8]='hmb_request_seq';put(vd+40,900000)
for i,p in ipairs({c1,c2}) do
 put(p,base+0x29a83d8);put(p+16,base+0x29a84b8);put(p+24,62);put(p+28,i)
 local province=p+0x1000;put(p+56,province);put(province+164,i*100)
 for j,offset in ipairs({40,48}) do
  local cb=p+0x2000+j*0x1000;local list=cb+0x100;local army=cb+0x200
  put(p+offset,cb);put(cb+44,1);put(cb+32,list);put(list,army)
  put(army,base+0x295a2b0);put(army+472,j)
 end
end
local fake={read_u64=read,read_u32=read,read_u8=read,base=function()return base end,
 read_str=function(p)return str[p]end,read_cstr=function(p)return str[p]end,
 scope_country=function()return 1 end,game_pause=function()pauses=pauses+1;return true end,
 effect=function(name,fn)assert(name=='hmb_capture_combat_selection' or name=='hmb_selection_ready');callbacks[name]=fn end}
local env=setmetatable({hoi4=fake,HMB_SELECTION={records={},order={}}},{__index=_G})
assert(load(SOURCE,'selection_reader_test','t',env))()
local m=env.HMB_SELECTION;local passed=0
local function check(v)assert(v,'Selection test failed at '..tostring(passed+1));passed=passed+1 end
put(view+48,62);put(view+52,2)
check(m.selected(g,'GER').combat=='2:62')
check(m.selected(g,'GER').province==200)
local captured=m.capture(0);check(captured.seq==9 and captured.combat=='2:62' and pauses==1)
put(view+52,1)
check(m.read('GER',9):find('"combat":"2:62"',1,true)~=nil)
check(m.selected(g,'GER').combat=='1:62')
check(m.read('GER',10):find('error',1,true)~=nil)
put(view+52,99);check(not pcall(m.selected,g,'GER'))
put(view+52,0);check(not pcall(m.selected,g,'GER'))
put(view+52,2);put(view+48,61);check(not pcall(m.selected,g,'GER'))
put(view+48,62);put(view,base+1);check(not pcall(m.selected,g,'GER'))
put(view,base+0x29de3b0);check(not pcall(m.selected,g,'USA'))
put(c1+28,2);check(not pcall(m.selected,g,'GER'));put(c1+28,1)
put(view+52,99);put(vd+40,1000000)
check(m.capture(0).error~=nil)
check(m.read('GER',10):find('error',1,true)~=nil)
put(cc+536,0);callbacks.hmb_capture_combat_selection(nil,nil,0)
check(next(m.records)==nil)
check(m.read('GER',9):find('error',1,true)~=nil)
callbacks.hmb_selection_ready();check(m.ready==1)
return '{"checks":'..tostring(passed)..',"real_game_reads":false,"real_game_writes":false,"real_module_unchanged":true}'
'''

def main():
    source=(ROOT/'hoi4_mod/lua/hmb_selection.lua').read_text(encoding='utf8')
    program='local original=HMB_SELECTION; local original_reader=original and original.selected; local SOURCE='+json.dumps(source)+'\nlocal function run_test()\n'+HARNESS+'\nend\nlocal report=run_test(); assert(HMB_SELECTION==original and (not original or original.selected==original_reader),"Mock leaked into the real module"); return report'
    response=NativeHOI().request('/lua',program)
    report=json.loads(response['result'])
    write_json(ROOT/'native_trial/evidence/selection_reader_mock.json',report)
    print(report)

if __name__=='__main__':main()
