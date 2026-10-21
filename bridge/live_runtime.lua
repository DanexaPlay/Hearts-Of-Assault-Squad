-- Version-locked reader and engine operations for hoi4_lua 1.19.3.
-- Layout provenance: ari-20/hoi4_lua book sections 4.18 and 4.22.
HMB_LIVE = HMB_LIVE or { receipts = {} }
local M=HMB_LIVE
local r,u,b=hoi4.read_u64,hoi4.read_u32,hoi4.base()
local function ptr(x) assert(x and x>65536 and x<0x7fffffffffff,'Invalid pointer');return x end
local function count(x,max) assert(x and x>=0 and x<=max,'Invalid container');return x end
local function id(p) return tostring(u(p+28))..':'..tostring(u(p+24)) end
local function json(x)
 if type(x)=='nil' then return 'null' end
 if type(x)=='boolean' or type(x)=='number' then return tostring(x) end
 if type(x)=='string' then return '"'..x:gsub('\\','\\\\'):gsub('"','\\"'):gsub('\n','\\n'):gsub('\r','\\r'):gsub('\t','\\t')..'"' end
 local out={};for k,v in pairs(x) do out[#out+1]=json(tostring(k))..':'..json(v) end
 table.sort(out);return '{'..table.concat(out,',')..'}'
end
M.json=json
local function gs() return ptr(r(b+0x332F260)) end
local function tag(g,t)
 assert(t and t>=0 and t<count(u(g+868),4096),'Invalid tag')
 return hoi4.read_cstr(ptr(r(g+856))+32*t)
end
local function province(g,n)
 assert(n>0 and n<count(u(g+700),200000),'Invalid province')
 local p=ptr(r(ptr(r(g+688))+8*n));assert(u(p+164)==n,'Province index mismatch');return p
end
local function army(p)
 ptr(p);assert(r(p)==b+0x295a2b0 and r(p+16)==b+0x295a490,'Not an army');return p
end
local function unit_state(g,p,country)
 army(p);local state={id=id(p),addr=p,country=country,province=u(ptr(r(p+496))+164),
  template_id=u(ptr(r(p+952))+12),org=r(p+1064),hp=r(p+1056),manpower=0,
  manpower_values={},equipment={},path_count=u(p+524),full_path_count=u(p+556),
  combat_count=u(p+436),owner=tag(g,u(p+472)),logical_country=tag(g,u(p+480))}
 state.path={}
 local np=count(state.path_count,4096);local pd=np>0 and ptr(r(p+512)) or 0
 for i=0,np-1 do
  local pid=u(pd+4*i);local pp=province(g,pid)
  state.path[tostring(i)]={province=pid,controller=tag(g,u(pp+392))}
 end
 local d=ptr(r(p+992));local n=count(u(p+1004),64)
 for i=0,n-1 do
  local e=d+8*i;local amount=u(e+4);state.manpower=state.manpower+amount
  state.manpower_values[tostring(i)]={addr=e+4,tag=u(e),amount=amount}
 end
 local n=count(u(p+884),4096);local d=n>0 and ptr(r(p+872)) or 0
 for i=0,n-1 do
  local e=d+16*i;local v=ptr(r(e));local key=tostring(u(v+12))..':'..tostring(u(v+8))
  assert(not state.equipment[key],'Duplicate equipment entry')
  state.equipment[key]={addr=e+8,variant=v,amount=r(e+8)}
 end
 return state
end
function M.inspect(plan)
 local g=gs();local out={gs=g,base=b,hour=u(g+1128),campaign_id=hoi4.read_str(g+1832),units={},combats={},provinces={},occupants={},flags={}}
 local store=ptr(r(g+600));local nf=count(u(store+20),100000)
 local fd=nf>0 and ptr(r(store+8)) or 0
 local tokens=ptr(r(b+0x35E1AE0));local nt=count(u(b+0x35E1AB4),200000)
 for i=0,nf-1 do
  local e=fd+48*i;local key=u(e+8);assert(key and key<=nt,'Invalid flag token')
  local name=hoi4.read_str(tokens+32*key)
  if name and name:sub(1,4)=='hmb_' then out.flags[name]=hoi4.read_u16(e+40) end
 end
 local countries=ptr(r(g+784));local nc=count(u(g+796),4096)
 for c=0,nc-1 do
  local cc=r(countries+8*c)
  if cc and cc>65536 then
   local n=count(u(cc+668),100000);local d=n>0 and ptr(r(cc+656)) or 0
   local country=tag(g,u(cc+8))
   for i=0,n-1 do
    local p=army(r(d+8*i));local key=id(p);local loc=u(ptr(r(p+496))+164)
    if plan.units[key] then assert(not out.units[key],'Duplicate unit');out.units[key]=unit_state(g,p,country) end
    if plan.provinces[tostring(loc)] then
     out.occupants[key]={country=country,province=loc}
    end
   end
  end
 end
 local nc=count(u(g+628),100000);local d=nc>0 and ptr(r(g+616)) or 0
 for i=0,nc-1 do
  local p=ptr(r(d+8*i))
  if r(p)==b+0x29a83d8 then
   assert(r(p+16)==b+0x29a84b8,'Wrong land combat vtable')
   local key=id(p);local record={addr=p,province=u(ptr(r(p+56))+164),attacker={},defender={}}
   for _,side in ipairs({'attacker','defender'}) do
    local cb=ptr(r(p+(side=='attacker' and 40 or 48)))
    local n=count(u(cb+44),4096);local d=n>0 and ptr(r(cb+32)) or 0
    for j=0,n-1 do record[side][id(army(r(d+8*j)))]=true end
   end
   out.combats[key]=record
  end
 end
 for key,_ in pairs(plan.provinces) do local p=province(g,tonumber(key));out.provinces[key]={addr=p,controller=tag(g,u(p+392))} end
 return out
end
function M.organization(plan)
 -- Capture only readiness. Full result inspection additionally reads flags,
 -- equipment, manpower, paths, occupations and combats that are unused here.
 local g=gs();local out={campaign_id=hoi4.read_str(g+1832),hour=u(g+1128),units={}}
 local selected={};local countries=ptr(r(g+784));local nc=count(u(g+796),4096)
 for c=0,nc-1 do
  local cc=r(countries+8*c)
  if cc and cc>65536 then
   local n=count(u(cc+668),100000);local d=n>0 and ptr(r(cc+656)) or 0
   for i=0,n-1 do
    local p=ptr(r(d+8*i));local key=id(p)
    if plan.units[key] then assert(not selected[key],'Duplicate organisation unit');selected[key]=army(p) end
   end
  end
 end
 for key,_ in pairs(plan.units) do
  local p=assert(selected[key],'Missing organisation unit');local org=r(p+1064)
  -- CArmy cached CSubUnitDefinition +160 +8*60, fixed-point 1e-5.
  -- Read only: do not call GetMaxStrength/GetMaxOrganisation.
  local stats=ptr(r(p+312))
  local maximum=r(stats+640)
  assert(maximum and maximum>=100 and maximum<=100000000,'Invalid maximum organisation')
  assert(org>=0 and org<=100000000,'Invalid current organisation')
  out.units[key]={current=org/100000,maximum=maximum/100000}
 end
 return out
end
function M.cancel(plan)
 local state=M.inspect(plan)
 for key,_ in pairs(plan.units) do
  local p=assert(state.units[key],'Missing unit').addr
  assert(hoi4.call_u64(b+0xBFB4A0,p,0)~=nil,'CancelMovement failed')
 end
 return M.inspect(plan)
end
local function equal(a,c)
 if type(a)~=type(c) then return false end
 if type(a)~='table' then return a==c end
 for k,v in pairs(a) do if not equal(v,c[k]) then return false end end
 for k,_ in pairs(c) do if a[k]==nil then return false end end
 return true
end
function M.validate_cleanup(plan,current_state)
 -- Validate every division before writing any tactical casualty targets.
 for key,target in pairs(plan.targets) do
  local current=assert(current_state.units[key],'Division disappeared during cleanup')
  local original=plan.before.units[key]
  assert(current.manpower<=original.manpower and original.manpower-current.manpower<=math.max(1,math.ceil(original.manpower/100)),'Unexpected manpower change during cleanup')
  for vid,e in pairs(target.equipment) do
   local entry=assert(current.equipment[vid],'Equipment entry disappeared during cleanup')
   local delta=e.before-entry.amount
   local allowed=math.max(100000,math.ceil(e.before/100))
   assert(delta>=-100000 and delta<=allowed,'Unexpected equipment change during cleanup: '..key..'/'..vid..' delta='..delta..' allowed_loss='..allowed)
  end
 end
end
function M.strength_limit(unit)
 -- Verified in 1.19.3: SetStrength (C8F1D0) clamps through virtual
 -- GetMaxStrength (C825F0), which returns max(100, cached_stats[288h]).
 -- The getter needs an output pointer; read its cache instead of calling it.
 assert(r(r(unit.addr)+264)==b+0xC825F0,'Unexpected maximum-strength getter')
 local maximum=r(ptr(r(unit.addr+312))+648)
 assert(maximum and maximum>=0 and maximum<=10000000000,'Invalid maximum strength')
 return math.max(100,maximum)
end
function M.verify_result(plan,after)
 local limits={}
 for key,target in pairs(plan.targets) do
  local actual=assert(after.units[key],'Division disappeared')
  local original=assert(plan.before.units[key],'Missing original division')
  assert(actual.owner==original.owner and actual.logical_country==original.logical_country and actual.template_id==original.template_id,'Division identity changed')
  assert(actual.province==target.province and actual.manpower==target.manpower,'Location/manpower verification failed')
  local maximum=M.strength_limit(actual);local expected=math.min(target.hp,maximum)
  assert(math.abs(actual.org-target.org)<=1 and math.abs(actual.hp-expected)<=1,'Strength/organization verification failed: '..key..' hp='..actual.hp..' expected='..expected..' org='..actual.org..' expected_org='..target.org)
  limits[key]={requested=target.hp,maximum=maximum,expected=expected,actual=actual.hp}
  assert(actual.combat_count==0 and actual.path_count==0 and actual.full_path_count==0,'Combat/movement remained')
  for index,value in pairs(target.manpower_values) do
   local entry=assert(actual.manpower_values[index],'Missing manpower component')
   assert(entry.amount==value.value and entry.tag==original.manpower_values[index].tag,'Manpower component verification failed')
  end
  for vid,e in pairs(target.equipment) do
   assert((actual.equipment[vid] and actual.equipment[vid].amount or 0)==e.value,'Equipment verification failed')
  end
  for vid,e in pairs(actual.equipment) do assert(target.equipment[vid] or e.amount==0,'Unexpected equipment variant') end
 end
 assert(after.hour==plan.before.hour and after.campaign_id==plan.campaign_id,'Campaign advanced during return')
 assert(not after.combats[plan.combat_id],'Selected combat remained')
 for key,_ in pairs(plan.before.combats) do if key~=plan.combat_id then assert(after.combats[key],'Unrelated combat disappeared') end end
 local expected_controller=plan.winner=='attacker' and plan.country or plan.before.provinces[tostring(plan.province)].controller
 assert(after.provinces[tostring(plan.province)].controller==expected_controller,'Province controller verification failed')
 return limits
end
function M.finalize_verified(plan,expected)
 -- Receipt-only recovery. Never moves units or applies casualties again.
 local state=M.inspect(plan)
 assert(equal(state,expected),'Live state changed since recovery inspection')
 assert(state.flags['hmb_pending_'..plan.battle_id]==1 and not state.flags['hmb_'..plan.battle_id],'Missing pending return or already applied')
 M.verify_result(plan,state)
 hoi4.console('eval_effect set_global_flag = hmb_'..plan.battle_id..' clr_global_flag = hmb_pending_'..plan.battle_id..' log = HMB_APPLIED_'..plan.battle_id)
 local after=M.inspect(plan)
 M.verify_result(plan,after)
 assert(after.flags['hmb_'..plan.battle_id]==1 and not after.flags['hmb_pending_'..plan.battle_id],'Return flags not acknowledged')
 M.receipts[plan.campaign_id..':'..plan.battle_id]='applied'
 return after
end
function M.apply(plan)
 assert(hoi4.game_pause(1),'Cannot hold pause')
 local before=M.inspect(plan)
 assert(equal(before,plan.before),'Live state changed since preflight')
 assert(plan.campaign_id==before.campaign_id and plan.battle_id:match('^%x+$') and #plan.battle_id==32,'Invalid live plan')
 local receipt=plan.campaign_id..':'..plan.battle_id
 assert(not M.receipts[receipt],'Live result already attempted')
 assert(not before.flags['hmb_'..plan.battle_id] and not before.flags['hmb_pending_'..plan.battle_id],'Result already applied or pending')
 assert(hoi4.read_u8(before.gs+680)==0,'Combat manager is updating')
 M.receipts[receipt]='applying'
 hoi4.console('eval_effect set_global_flag = hmb_pending_'..plan.battle_id)
 assert(M.inspect(plan).flags['hmb_pending_'..plan.battle_id]==1,'Pending flag not acknowledged')
 -- Engine APIs maintain movement, province and combat back-references.
 for key,_ in pairs(plan.targets) do
  local p=before.units[key].addr
  assert(hoi4.call_u64(b+0xBFB4A0,p,0)~=nil,'CancelMovement failed')
 end
 for key,target in pairs(plan.targets) do
  if target.loser and target.province~=before.units[key].province then
   local n=u(before.units[key].addr+28)
   hoi4.console('moveunit '..n..' '..target.province)
   assert(M.inspect(plan).units[key].province==target.province,'Retreat move failed')
  end
 end
 local remaining=M.inspect(plan).combats[plan.combat_id]
 if remaining then
  assert(hoi4.call_u64(b+0xBBA1B0,before.gs+608,remaining.addr)~=nil,'RemoveCombat failed')
 end
 local detached=M.inspect(plan)
 assert(not detached.combats[plan.combat_id],'Selected combat remained active')
 for key,_ in pairs(plan.targets) do assert(detached.units[key].combat_count==0,'Unit still references combat') end
 -- Combat cleanup can reinstate the old attack path; cancel once detached too.
 for key,_ in pairs(plan.targets) do
  assert(hoi4.call_u64(b+0xBFB4A0,detached.units[key].addr,0)~=nil,'Detached movement cancellation failed')
 end
 if plan.winner=='attacker' then
  hoi4.console('eval_effect '..plan.country..' = { set_province_controller = '..plan.province..' }')
  assert(M.inspect(plan).provinces[tostring(plan.province)].controller==plan.country,'Province control failed')
  for key,target in pairs(plan.targets) do
   if not target.loser then
    hoi4.console('moveunit '..u(before.units[key].addr+28)..' '..target.province)
    assert(hoi4.call_u64(b+0xBFB4A0,before.units[key].addr,0)~=nil,'Winner movement cancellation failed')
   end
  end
 end
 -- Combat cleanup can flush pending casualties and round fractional gear.
 -- Bound losses to 1% (minimum one item), gains to one rounding unit, then
 -- reconcile absolute tactical targets. No second casualty subtraction.
 local cleaned=M.inspect(plan)
 M.validate_cleanup(plan,cleaned)
 for key,target in pairs(plan.targets) do
  local current=cleaned.units[key];local original=before.units[key]
  for vid,e in pairs(target.equipment) do
   local entry=current.equipment[vid]
   local loss=entry.amount-e.value
   if loss>0 then
    -- Equipment pool API updates both internal pools; raw variant writes do not.
    assert(hoi4.call_u64(b+0x1012850,current.addr+840,entry.variant,loss)~=nil,'Equipment removal failed')
   elseif loss<0 then
    assert(hoi4.call_u64(b+0x100CCE0,current.addr+840,entry.variant,-loss)~=nil,'Fractional equipment reconciliation failed')
   end
  end
  for index,entry in pairs(target.manpower_values) do
   local actual=assert(current.manpower_values[index],'Manpower entry disappeared')
   assert(actual.tag==original.manpower_values[index].tag and actual.amount<=entry.before,'Manpower ownership changed')
   assert(hoi4.write_u32(actual.addr,entry.value),'Manpower write failed')
  end
  assert(hoi4.call_u64(r(r(current.addr)+22*8),current.addr)~=nil,'RefreshAbilities failed')
  assert(hoi4.call_u64(b+0xC8F1D0,current.addr,target.hp)~=nil,'SetStrength failed')
  assert(hoi4.call_u64(b+0xC8F170,current.addr,target.org)~=nil,'SetOrganisation failed')
 end
 local after=M.inspect(plan)
 M.verify_result(plan,after)
 hoi4.console('eval_effect set_global_flag = hmb_'..plan.battle_id..' clr_global_flag = hmb_pending_'..plan.battle_id..' log = HMB_APPLIED_'..plan.battle_id)
 after=M.inspect(plan);assert(after.flags['hmb_'..plan.battle_id]==1,'Applied flag missing')
 M.receipts[receipt]='applied'
 return after
end
return 'live runtime ready'
