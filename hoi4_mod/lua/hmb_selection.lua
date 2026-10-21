-- HOI4 1.19.3 / hoi4_lua v0.5. Capture the combat view's target during
-- the button effect, before the player can open another combat window.
-- Only reads verified layouts and uses the runtime's existing pause API.
HMB_SELECTION = HMB_SELECTION or {records={},order={}}
local M=HMB_SELECTION
local r,u,b=hoi4.read_u64,hoi4.read_u32,hoi4.base()
local function ptr(p) assert(p and p>65536 and p<0x7fffffffffff,'Invalid selection pointer');return p end
local function count(n,max) assert(n and n>=0 and n<=max,'Invalid selection container');return n end
local function gs() return ptr(r(b+0x332F260)) end
local function key(g,c,s) return tostring(g)..':'..c..':'..tostring(s) end
local function tag(g,t)
 assert(t and t>=0 and t<count(u(g+868),4096),'Invalid selection country')
 return assert(hoi4.read_cstr(ptr(r(g+856))+32*t),'Missing selection country')
end
local function country(g,ctx)
 local index=hoi4.scope_country(ctx)
 assert(index and index>0 and index<count(u(g+796),4096),'Button country scope missing')
 local cc=ptr(r(ptr(r(g+784))+8*index))
 return cc,tag(g,u(cc+8))
end
local function sequence(cc)
 local vars=ptr(r(cc+536));local n=count(u(vars+32),262144)
 assert(n>0,'Button sequence missing')
 local mask=count(u(vars+36),262143);local extra=count(hoi4.read_u8(vars+40),255)
 local data=ptr(r(vars+24));local found
 for i=0,mask+extra do
  local p=data+48*i;local dist=assert(u(p+4))&255
  if dist~=0 and dist~=254 and dist~=255 and hoi4.read_str(p+8)=='hmb_request_seq' then
   assert(not found,'Duplicate button sequence')
   local value=r(p+40);assert(value and value>0 and value%100000==0,'Invalid button sequence')
   found=value//100000
  end
 end
 assert(found and found<1000000000,'Button sequence missing');return found
end
function M.selected(g,c)
 local idler=ptr(r(b+0x332F698));assert(r(idler)==b+0x2968ff0,'Unsupported in-game interface')
 local handler=ptr(r(idler+1720));local view=ptr(r(handler+504))
 assert(r(view)==b+0x29de3b0,'Unsupported combat view')
 local typ,index=u(view+48),u(view+52)
 assert(typ==62 and index and index>0,'No land combat selected')
 local n=count(u(g+628),100000);local data=n>0 and ptr(r(g+616)) or 0
 local found
 for i=0,n-1 do
  local p=ptr(r(data+8*i))
  if r(p)==b+0x29a83d8 and u(p+24)==typ and u(p+28)==index then
   assert(not found,'Ambiguous combat view target');assert(r(p+16)==b+0x29a84b8,'Unsupported combat object')
   local province=ptr(r(p+56));local province_id=u(province+164)
   assert(province_id and province_id>0 and province_id<count(u(g+700),200000),'Invalid combat province')
   local involved=false
   for _,offset in ipairs({40,48}) do
    local cb=ptr(r(p+offset));local units=count(u(cb+44),4096);local list=units>0 and ptr(r(cb+32)) or 0
    for j=0,units-1 do
     local army=ptr(r(list+8*j));assert(r(army)==b+0x295a2b0,'Unsupported combat unit')
     if tag(g,u(army+472))==c then involved=true end
    end
   end
   assert(involved,'Player is not participating in the selected combat')
   found={combat=tostring(index)..':'..tostring(typ),province=province_id,
      campaign_id=hoi4.read_str(g+1832),game_hour=u(g+1128),country=c,source='combat_button_effect_v1'}
  end
 end
 assert(found,'Selected combat no longer exists');return found
end
function M.capture(ctx)
 local g=gs();local cc,c=country(g,ctx);local seq=sequence(cc);local k=key(g,c,seq)
 local ok,record=pcall(function()
  local selected=M.selected(g,c)
  assert(hoi4.game_pause(1),'Could not pause selected combat')
  assert(u(g+1128)==selected.game_hour,'Campaign advanced during combat selection')
  selected.seq=seq;return selected
 end)
 if not ok then record={error=tostring(record),country=c,seq=seq} end
 if not M.records[k] then M.order[#M.order+1]=k end
 M.records[k]=record
 while #M.order>64 do M.records[table.remove(M.order,1)]=nil end
 return record
end
local function json(v)
 if type(v)=='nil' then return 'null' end
 if type(v)=='number' or type(v)=='boolean' then return tostring(v) end
 if type(v)=='string' then return '"'..v:gsub('\\','\\\\'):gsub('"','\\"'):gsub('\n','\\n'):gsub('\r','\\r'):gsub('\t','\\t')..'"' end
 local out={};for k,x in pairs(v) do out[#out+1]=json(tostring(k))..':'..json(x) end
 table.sort(out);return '{'..table.concat(out,',')..'}'
end
function M.read(c,seq) return json(M.records[key(gs(),c,seq)] or {error=M.last_error or 'No combat selection captured for this button press'}) end
hoi4.effect('hmb_capture_combat_selection',function(_,self,ctx)
 local ok,err=pcall(M.capture,ctx)
 if not ok then
  -- A failure before reading the sequence must not expose a record left
  -- behind by an earlier load of the same campaign and sequence number.
  M.records={};M.order={};M.last_error=tostring(err)
 else M.last_error=nil end
end)
hoi4.effect('hmb_selection_ready',function() M.ready=(M.ready or 0)+1 end)
