-- Leased native lab floor in the same rigid frame as the visible weapon.
-- The guest arena remains active for the body. Only verified weapon components
-- switch to the proxy, after its own collision query succeeds.
return function(api,pawn,session)
    local base=(HALFLIGHT_ROOT.."/work/lab/")
    local held_weapon=assert(loadfile((HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_held_weapon.lua")))()(api,pawn)
    local packets=assert(loadfile((HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_packet_reader.lua")))()(base..'guest-floor-'..session..'.txt',8192)
    local M={sequence=0,last=-1,physics=false,armed=false,error='none',trace_error='none',saved={}}
    local function numbers(text,count)
        local result={}
        for token in assert(text,'Missing numeric field'):gmatch('[^,]+') do
            local n=assert(tonumber(token));assert(n==n and math.abs(n)<1e6,'Invalid collider number');result[#result+1]=n
        end
        assert(#result==count,'Invalid collider field length');return result
    end
    local function vector(v) return {X=v[1],Y=v[2],Z=v[3]} end
    local function restore_weapon()
        for _,saved in ipairs(M.saved) do
            if api.valid(saved.part) then
                pcall(function()
                    saved.part:SetCollisionResponseToChannel(0,saved.world);saved.part:SetCollisionResponseToChannel(31,saved.proxy)
                    if saved.ccd~=nil then saved.part:SetUseCCD(saved.ccd,saved.bone) end
                end)
            end
        end
        M.saved={};M.armed=false;M.weapon=nil
    end
    local function remove()
        restore_weapon()
        if api.valid(M.actor) then pcall(function() M.actor:K2_DestroyActor() end) end
        M.actor=nil;M.component=nil;M.physics=false;M.transform=nil;M.last_check=nil;M.last_weapon_check=nil
    end
    function M:stop() remove() end
    function M:close() packets:close() end
    local function current_weapon()
        local f=io.open(base..'guest-live-weapon-'..session..'.txt','rb')
        local expected=f and f:read('*a') or '';if f then f:close() end
        local weapon,hand=held_weapon();local other=held_weapon(hand=='R' and 'L' or 'R')
        local function verified(value)
            if not api.valid(value) then return nil end
            for name in (expected..'\n'):gmatch('([^\r\n]+)') do if name==api.safe_text(value) then return value end end
        end
        weapon=verified(weapon);other=verified(other)
        if other and api.safe_text(other)==api.safe_text(weapon) then other=nil end
        return weapon,other
    end
    local function arm(weapon,other)
        local function collect(weapon)
        local root=api.read(weapon,'RootComponent')
        assert(api.valid(root) and root:GetCollisionObjectType()==14,'Verified weapon root required')
        local parts=weapon:K2_GetComponentsByClass(StaticFindObject('/Script/Engine.PrimitiveComponent'))
        local function save(part)
            if not api.valid(part) then part=part:get() end
            if api.valid(part) and part:GetCollisionObjectType()==14 and part:GetCollisionEnabled()~=0 then
                local world,proxy=part:GetCollisionResponseToChannel(0),part:GetCollisionResponseToChannel(31)
                assert(world>=0 and world<=2 and proxy>=0 and proxy<=2,'Unexpected collision mask')
                local ccd=api.read(api.read(part,'BodyInstance'),'bUseCCD')
                if type(ccd)~='boolean' then ccd=nil end
                local bone=api.call(part,'GetAttachSocketName')
                local bone_name=bone and api.call(bone,'ToString') or 'unavailable'
                if bone_name~='None' and bone_name~='' then ccd=nil end
                M.saved[#M.saved+1]={part=part,world=world,proxy=proxy,ccd=ccd,bone=bone}
            end
        end
        if type(parts)=='table' and parts.ForEach==nil then for _,part in pairs(parts) do save(part) end
        else parts:ForEach(function(_,wrapped) save(wrapped:get()) end) end
        end
        collect(weapon);if api.valid(other) then collect(other) end
        assert(#M.saved>0,'No active weapon primitives')
        for _,saved in ipairs(M.saved) do
            saved.part:SetCollisionResponseToChannel(31,2);saved.part:SetCollisionResponseToChannel(0,0)
            if saved.ccd~=nil then saved.part:SetUseCCD(true,saved.bone) end
            assert(saved.part:GetCollisionResponseToChannel(31)==2 and saved.part:GetCollisionResponseToChannel(0)==0,'Weapon mask did not change')
        end
        M.weapon=api.safe_text(weapon)..'|'..api.safe_text(other);M.armed=true
    end
    local function refresh_weapon(real)
        if M.last_weapon_check and real-M.last_weapon_check<.25 then return end
        M.last_weapon_check=real
        local weapon,other=current_weapon()
        if M.armed and (not api.valid(weapon) or api.safe_text(weapon)..'|'..api.safe_text(other)~=M.weapon) then restore_weapon() end
        if M.trace and not M.armed and api.valid(weapon) then arm(weapon,other) end
    end
    function M:sample(real)
        if real-self.last<1/60 then return end;self.last=real
        local ok,err=pcall(function()
            local text=packets:read()
            if not text then if self.expiry and os.time()<self.expiry then return end;remove();return end
            local v={}
            for key,value in text:gmatch('([%w_]+)=([^\r\n]+)') do assert(v[key]==nil,'Duplicate collider field');v[key]=value end
            local expiry=tonumber(v.expires_at) or 0
            if v.Session~=session or v.mode~='rigid-floor' or v.source~='dl2-lab-floor' or v.units~='guest-centimetres' or
               v.seq~=v.end_seq or expiry<=os.time() or expiry>os.time()+3 then remove();return end
            local sequence=assert(tonumber(v.seq));assert(sequence>0);self.expiry=expiry
            if sequence<=self.sequence then refresh_weapon(real);return end
            local t=numbers(v.transform,7);assert(math.abs(t[4]^2+t[5]^2+t[6]^2+t[7]^2-1)<.001,'Collider rotation invalid')
            if not api.valid(self.component) then
                assert(v.triangle_count=='2','Expected actual two-triangle platform')
                -- Exact source box: 30 m square, 5 cm thick. A simple
                -- solid shape also avoids triangle-mesh collision cooking.
                assert(v.triangle_0=='-1500,-1500,0,1500,-1500,0,1500,1500,0' and v.triangle_1=='-1500,-1500,0,1500,1500,0,-1500,1500,0','Unexpected platform dimensions')
                local world=api.call(pawn,'GetWorld')
                self.actor=world:SpawnActor(StaticFindObject('/Script/Engine.Actor'),{X=0,Y=0,Z=0},{Pitch=0,Yaw=0,Roll=0})
                assert(api.valid(self.actor),'Collider actor missing')
                self.component=self.actor:AddComponentByClass(StaticFindObject('/Script/Engine.BoxComponent'),false,{Translation={X=0,Y=0,Z=0},Rotation={X=0,Y=0,Z=0,W=1},Scale3D={X=1,Y=1,Z=1}},false)
                assert(api.valid(self.component),'Collider component missing')
                self.actor:SetActorHiddenInGame(true);self.component:SetVisibility(false,false);self.component:SetHiddenInGame(true,false)
                self.component:SetCollisionEnabled(0);self.component:SetMobility(2)
                self.component:SetCollisionObjectType(31);self.component:SetCollisionResponseToAllChannels(0);self.component:SetCollisionResponseToChannel(14,2)
                self.component:SetBoxExtent({X=1500,Y=1500,Z=2.5},false)
                self.component:SetCollisionEnabled(3);self.geometry_id=v.geometry_id
            end
            assert(v.geometry_id==self.geometry_id,'Collider topology changed')
            local ray_start=numbers(v.trace_start,3);local ray_end=numbers(v.trace_end,3)
            local transform={Translation={X=t[1]-.025*(ray_start[1]-ray_end[1]),Y=t[2]-.025*(ray_start[2]-ray_end[2]),Z=t[3]-.025*(ray_start[3]-ray_end[3])},Rotation={X=t[4],Y=t[5],Z=t[6],W=t[7]},Scale3D={X=1,Y=1,Z=1}}
            -- Move a kinematic collider through physics, rather than teleporting
            -- a thin floor four times per second past a swinging rigid body.
            local packed={transform.Translation.X,transform.Translation.Y,transform.Translation.Z,t[4],t[5],t[6],t[7]}
            local changed=not self.transform
            if self.transform then for i=1,7 do
                if math.abs(packed[i]-self.transform[i])>(i<=3 and .01 or .000001) then changed=true;break end
            end end
            if changed then
                assert(self.actor:K2_SetActorTransform(transform,false,{},false),'Collider transform rejected');self.transform=packed
            end
            self.sequence=sequence
            if not self.last_check or real-self.last_check>=.25 then
                self.last_check=real
                self.physics=self.component:GetCollisionEnabled()==3
                assert(self.component:GetCollisionObjectType()==31 and self.component:GetCollisionResponseToChannel(14)==2 and self.component:GetCollisionResponseToChannel(2)==0 and self.component:GetCollisionResponseToChannel(16)==0,'Collider masks changed')
                local traced,hit=pcall(function() return self.component:K2_LineTraceComponent(vector(ray_start),vector(ray_end),false,false,false,{},{},{},{}) end)
                self.trace=traced and hit==true
                self.trace_error=traced and 'none' or tostring(hit):gsub('[\r\n=]',' '):sub(1,220)
            end
            refresh_weapon(real)
        end)
        if not ok then self.error=tostring(err):gsub('[\r\n=]',' '):sub(1,240);remove() end
        if self.status_time and real-self.status_time<1 then return end;self.status_time=real
        local status=io.open(base..'guest-floor-status-'..session..'.txt','wb')
        if status then
            status:write('shape=solid-box\nphysics='..(self.physics and '1' or '0')..'\narmed='..(self.armed and '1' or '0')..'\nweapon_components='..#self.saved..'\nsequence='..self.sequence..'\ntrace_hit='..tostring(self.trace)..'\ntrace_error='..self.trace_error..'\nerror='..self.error..'\nupdate_hz=60\nteleport=false\n')
            for i,saved in ipairs(self.saved) do
                status:write('part_'..i..'='..api.safe_text(saved.part)..'|enabled='..tostring(api.call(saved.part,'GetCollisionEnabled'))..'|simulating='..tostring(api.call(saved.part,'IsAnySimulatingPhysics'))..'|world='..tostring(api.call(saved.part,'GetCollisionResponseToChannel',0))..'|proxy='..tostring(api.call(saved.part,'GetCollisionResponseToChannel',31))..'|ccd_saved='..tostring(saved.ccd)..'\n')
            end
            status:close()
        end
    end
    return M
end
