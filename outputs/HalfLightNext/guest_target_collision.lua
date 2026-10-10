-- Leased body proxies for the verified nearby DL2 enemies.
-- Enemy body/weapon capsules are queries; impact resistance is explicit.
return function(api,pawn,session)
    local timed=api.timed or function(_,fn) fn() end
    local base=(HALFLIGHT_ROOT.."/work/lab/")
    local packets=assert(loadfile((HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_packet_reader.lua")))()(base..'guest-target-'..session..'.txt',98304)
    local registry
    local M={sequence=0,last=-1,error='none',physics=false,trace=false,proxies={},spares={},count=0,impact_sequence=0,resisted=0,stuck=0,broken=0,active_bites=0,max_bite_seconds=0,max_stance_drift_cm=0,stance={}}
    local function numbers(text,count)
        local result={}
        for value in assert(text,'Missing target field'):gmatch('[^,]+') do
            local n=assert(tonumber(value));assert(n==n and math.abs(n)<1e6);result[#result+1]=n
        end
        assert(#result==count);return result
    end
    local function vector(v)return {X=v[1],Y=v[2],Z=v[3]} end
    local function different(a,b)
        if not a then return true end
        for i=1,7 do if math.abs(a[i]-b[i])>(i<=3 and .01 or .000001) then return true end end
        return false
    end
    local function remove(proxy)
        if api.valid(proxy.actor) then pcall(function() proxy.actor:K2_DestroyActor() end) end
    end
    local function retire(proxy)
        if api.valid(proxy.component) then
            proxy.component:SetCollisionEnabled(0);proxy.enabled=false;proxy.t=nil;proxy.check_time=nil
            if #M.spares<224 then M.spares[#M.spares+1]=proxy;return end
        end
        remove(proxy)
    end
    local function constraint(holder,position)
        if not api.valid(holder.constraint) then
            holder.actor=pawn:GetWorld():SpawnActor(StaticFindObject('/Script/Engine.Actor'),position,{Pitch=0,Yaw=0,Roll=0})
            assert(api.valid(holder.actor),'Constraint actor unavailable')
            holder.constraint=holder.actor:AddComponentByClass(StaticFindObject('/Script/Engine.PhysicsConstraintComponent'),false,
                {Translation={X=0,Y=0,Z=0},Rotation={X=0,Y=0,Z=0,W=1},Scale3D={X=1,Y=1,Z=1}},false)
            assert(api.valid(holder.constraint),'Constraint unavailable')
            holder.constraint:SetDisableCollision(true)
        end
        holder.constraint:K2_SetWorldLocation(position,false,{},false)
        return holder.constraint
    end
    function M:hold_stance()
        if api.read(pawn,'Fallen')==true or api.read(pawn,'Ded')==true then
            if self.stance.bound then self.stance.constraint:BreakConstraint();self.stance.bound=false end
            return
        end
        local mesh=api.read(pawn,'Mesh')
        assert(api.valid(mesh) and mesh:IsSimulatingPhysics(FName('pelvis')),'Simulated pelvis unavailable')
        local position=mesh:GetSocketLocation(FName('pelvis'))
        if self.stance.bound then
            self.max_stance_drift_cm=math.max(self.max_stance_drift_cm,math.sqrt((position.X-self.stance.position.X)^2+(position.Y-self.stance.position.Y)^2))
            return
        end
        local c=constraint(self.stance,position);self.stance.position={X=position.X,Y=position.Y}
        c:SetLinearXLimit(2,0);c:SetLinearYLimit(2,0);c:SetLinearZLimit(0,0)
        c:SetAngularSwing1Limit(0,0);c:SetAngularSwing2Limit(0,0);c:SetAngularTwistLimit(0,0)
        -- Only horizontal translation is held; native balance, height and arm physics remain active.
        c:SetConstrainedComponents(mesh,FName('pelvis'),nil,FName('None'));self.stance.bound=true
    end
    local function responses(real,v)
        M.real=real;M.active_bites=0
        -- Enemy motion must never constrain a source weapon held by the ragdoll.
        -- Sticking is now applied only to the DL2 presentation pose.
        local count=tonumber(v.impact_count) or 0;assert(count>=0 and count<=64 and count%1==0)
        if count>0 and not registry then registry=assert(loadfile((HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_weapon_catalog.lua")))()(api) end
        for i=0,count-1 do
            local values=numbers(v['impact_'..i],11);local seq,bank,region,force,stick=table.unpack(values,1,5)
            assert(seq%1==0 and seq>0 and bank%1==0 and bank>=0 and bank<registry.count*2 and region%1==0 and region>=0 and region<14)
            assert(force>=.1 and force<=3 and stick>=0 and stick<=.6)
            assert(math.abs(values[9]^2+values[10]^2+values[11]^2-1)<.01)
            local entity=assert(v['impact_'..i..'_entity']);assert(entity:match('^0x[%da-f]+$'))
            if seq>M.impact_sequence then
                M.impact_sequence=seq
                local side=bank>=registry.count and 'L' or 'R';local weapon=api.read(pawn,'Weapon '..side)
                local index=registry:match(weapon);local part=api.valid(weapon) and api.read(weapon,'RootComponent');local proxy=M.proxies[entity..':'..region]
                if index==bank%registry.count and api.valid(part) and proxy and api.valid(proxy.component) and part:IsSimulatingPhysics(FName('None')) then
                    local velocity=part:GetPhysicsLinearVelocity(FName('None'));local angular=part:GetPhysicsAngularVelocityInRadians(FName('None'))
                    local retention=region>=12 and .3 or .65
                    part:SetPhysicsLinearVelocity({X=velocity.X*retention,Y=velocity.Y*retention,Z=velocity.Z*retention},false,FName('None'))
                    part:SetPhysicsAngularVelocityInRadians({X=angular.X*retention,Y=angular.Y*retention,Z=angular.Z*retention},false,FName('None'))
                    M.resisted=M.resisted+1

                end
            end
        end
    end
    -- Read-only reflected API check for contact damping and the pelvis stance.
    local api_ok,api_error=pcall(function()
        local required={PhysicsConstraintComponent={'SetLinearXLimit','SetLinearYLimit','SetLinearZLimit','SetAngularSwing1Limit','SetAngularSwing2Limit','SetAngularTwistLimit','SetDisableCollision','SetLinearBreakable','SetConstrainedComponents','SetConstraintReferencePosition','BreakConstraint','IsBroken'},
            SceneComponent={'K2_SetWorldLocation'},PrimitiveComponent={'IsSimulatingPhysics','GetPhysicsLinearVelocity','GetPhysicsAngularVelocityInRadians','SetPhysicsLinearVelocity','SetPhysicsAngularVelocityInRadians','WakeAllRigidBodies','GetMass'}}
        local found={}
        for class_name,names in pairs(required) do
            local class=StaticFindObject('/Script/Engine.'..class_name);assert(api.valid(class),class_name..' missing')
            class:ForEachFunction(function(fn) found[fn:GetFName():ToString()]=true end)
        end
        for class_name,names in pairs(required) do for _,name in ipairs(names) do assert(found[name],class_name..'.'..name..' missing') end end
        local catalog=assert(loadfile((HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_weapon_catalog.lua")))()(api)
        local weapon=api.read(pawn,'Weapon R');local index=catalog:match(weapon)
        local part=index and api.read(weapon,'RootComponent')
        if api.valid(part) then
            part:IsSimulatingPhysics(FName('None'));part:GetPhysicsLinearVelocity(FName('None'))
            part:GetPhysicsAngularVelocityInRadians(FName('None'));assert(part:GetMass()>0,'Striking part mass unavailable')
        end
    end)
    local api_status=io.open(base..'guest-combat-api-'..session..'.txt','wb')
    if api_status then api_status:write('Session='..session..'\nreflected_api='..tostring(api_ok)..'\nerror='..tostring(api_error or 'none'):gsub('[\r\n]',' ')..'\n');api_status:close() end
    function M:stop()
        if self.stance.bound then self.stance.constraint:BreakConstraint();self.stance.bound=false end
        -- Expiry disables collision immediately; recovery reuses the owned
        -- components instead of spawning/destroying twelve actors per target.
        for _,proxy in pairs(self.proxies) do retire(proxy) end
        self.proxies={};self.count=0;self.active_bites=0;self.physics=false;self.trace=false;self.physics_count=0;self.query_count=0;self.trace_count=0
    end
    function M:close()
        self:stop()
        if api.valid(self.stance.actor) then self.stance.actor:K2_DestroyActor() end;self.stance={}
        for _,proxy in pairs(self.proxies) do remove(proxy) end
        for _,proxy in ipairs(self.spares) do remove(proxy) end
        self.proxies={};self.spares={};packets:close()
    end
    function M:sample(real)
        if real-self.last<1/60 then return end;self.last=real
        local ok,err=pcall(function()
            if not self.control_time or real-self.control_time>=.5 then
                self.control_time=real
                local control=io.open(base..'guest-target-collision.ini','rb')
                local setting=control and control:read(256) or '';if control then control:close() end
                self.disabled=setting:match('Enabled=0')~=nil
            end
            if self.disabled then self:stop();return end
            local text;timed('target_read',function() text=packets:read() end)
            if not text then if self.expiry and os.time()<self.expiry then responses(real,{impact_count='0'});return end;self:stop();return end
            local v={}
            for k,value in text:gmatch('([%w_]+)=([^\r\n]+)') do assert(v[k]==nil);v[k]=value end
            local expiry=tonumber(v.expires_at) or 0
            if v.Session~=session or v.source~='dl2-native-target' or v.mode~='target-capsules' or
                v.units~='guest-centimetres' or v.seq~=v.end_seq or expiry<=os.time() or expiry>os.time()+3 then self:stop();return end
            local sequence=assert(tonumber(v.seq));assert(sequence>0);self.expiry=expiry
            if sequence<=self.sequence then responses(real,{impact_count='0'});return end
            local count=assert(tonumber(v.target_count));assert(count>=0 and count<=224 and count%1==0)
            local rows,seen={},{}
            -- Validate the entire snapshot before touching any physics actor.
            for i=0,count-1 do
                local prefix='target_'..i..'_'
                local handle=assert(v[prefix..'handle']);assert(handle:match('^0x[%da-f]+$'))
                local region=assert(tonumber(v[prefix..'region']));assert(region>=0 and region<14 and region%1==0)
                handle=handle..':'..region;assert(not seen[handle]);seen[handle]=true
                local t=numbers(v[prefix..'transform'],7);assert(math.abs(t[4]^2+t[5]^2+t[6]^2+t[7]^2-1)<.001)
                local radius,half=assert(tonumber(v[prefix..'radius'])),assert(tonumber(v[prefix..'half_height']))
                assert(radius>=(region>=12 and 2.5 or 4) and radius<=60 and half<=180 and half>radius)
                rows[#rows+1]={handle=handle,t=t,radius=radius,half=half,
                    a=numbers(v[prefix..'trace_start'],3),b=numbers(v[prefix..'trace_end'],3)}
            end
            for handle,proxy in pairs(self.proxies) do if not seen[handle] then retire(proxy);self.proxies[handle]=nil end end
            local physics,queries,trace=0,0,0
            for _,row in ipairs(rows) do
                local proxy=self.proxies[row.handle]
                if not proxy or not api.valid(proxy.component) then
                    if proxy then remove(proxy) end
                    proxy=table.remove(self.spares) or {};self.proxies[row.handle]=proxy
                    if not api.valid(proxy.component) then
                    proxy.actor=pawn:GetWorld():SpawnActor(StaticFindObject('/Script/Engine.Actor'),{X=0,Y=0,Z=0},{Pitch=0,Yaw=0,Roll=0})
                    assert(api.valid(proxy.actor),'Target proxy actor missing')
                    proxy.component=proxy.actor:AddComponentByClass(StaticFindObject('/Script/Engine.CapsuleComponent'),false,
                        {Translation={X=0,Y=0,Z=0},Rotation={X=0,Y=0,Z=0,W=1},Scale3D={X=1,Y=1,Z=1}},false)
                    assert(api.valid(proxy.component),'Target capsule missing')
                    proxy.actor:SetActorHiddenInGame(true);proxy.component:SetVisibility(false,false);proxy.component:SetHiddenInGame(true,false)
                    proxy.component:SetCollisionEnabled(0);proxy.component:SetMobility(2)
                    proxy.component:SetCollisionObjectType(31);proxy.component:SetCollisionResponseToAllChannels(0)
                    proxy.component:SetCollisionResponseToChannel(14,2)
                    end
                end
                -- Resizing recreates physics state. Keep a stationary body's
                -- shape and collision mode intact between real changes.
                if not proxy.radius or math.abs(proxy.radius-row.radius)>.05 or math.abs(proxy.half-row.half)>.05 then
                    proxy.component:SetCapsuleSize(row.radius,row.half,false)
                    proxy.radius=row.radius;proxy.half=row.half
                end
                local t=row.t
                local transform={Translation=vector(t),Rotation={X=t[4],Y=t[5],Z=t[6],W=t[7]},Scale3D={X=1,Y=1,Z=1}}
                if different(proxy.t,t) then
                    timed('target_transform',function() assert(proxy.actor:K2_SetActorTransform(transform,false,{},false),'Target transform rejected') end);proxy.t=t
                end
                local mode=1 -- Enemy motion supplies queries, never forces on the source ragdoll.
                if proxy.enabled~=mode then proxy.component:SetCollisionEnabled(mode);proxy.enabled=mode end
                if not proxy.check_time or real-proxy.check_time>=.5 then
                    proxy.check_time=real
                    timed('target_probe',function()
                        local enabled=proxy.component:GetCollisionEnabled()
                        proxy.physics=enabled==3;proxy.query=enabled==1
                        proxy.trace=proxy.component:K2_LineTraceComponent(vector(row.a),vector(row.b),false,false,false,{},{},{},{})==true
                    end)
                end
                if proxy.physics then physics=physics+1 end
                if proxy.query then queries=queries+1 end
                if proxy.trace then trace=trace+1 end
            end
            self.count=count;self.physics=physics>0;self.trace=trace==count and count>0
            self.physics_count=physics;self.query_count=queries;self.trace_count=trace;self.sequence=sequence;self.error='none'
            responses(real,v)
        end)
        if not ok then self.error=tostring(err):gsub('[\r\n=]',' '):sub(1,240);self:stop() end
        if not self.status_time or real-self.status_time>=.5 then
            self.status_time=real
            local f=io.open(base..'guest-target-status-'..session..'.txt','wb')
            if f then f:write('shape=animated-body-region-capsules\nphysics='..(self.physics and '1' or '0')..'\ntrace_hit='..tostring(self.trace)..
                '\nsequence='..self.sequence..'\ntarget_count='..self.count..'\nphysics_count='..(self.physics_count or 0)..
                '\nquery_count='..(self.query_count or 0)..'\ntrace_count='..(self.trace_count or 0)..'\ncontact_responses='..self.resisted..'\nbites='..self.stuck..'\nactive_bites='..self.active_bites..'\nbroken_bites='..self.broken..'\nmax_bite_seconds='..self.max_bite_seconds..'\nmax_stance_drift_cm='..self.max_stance_drift_cm..'\nstance_anchored='..tostring(self.stance.bound==true)..'\nbody_collision=query-only;weapon_collision=query-only;sticking=host-presentation\nerror='..self.error..'\nnative_damage=0\n');f:close() end
        end
    end
    return M
end
