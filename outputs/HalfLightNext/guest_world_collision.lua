-- Original weapon-only collision back-channel for the native test platform.
-- Reuses the reflected procedural-mesh route verified in this owned install.
return function(api,pawn,session)
    local base=(HALFLIGHT_ROOT.."/work/lab/")
    local M={actor=nil,component=nil,sequence=0,last=-1,error='none',physics=false}
    local function remove()
        if api.valid(M.actor) then pcall(function() M.actor:K2_DestroyActor() end) end
        M.actor=nil;M.component=nil;M.physics=false
    end
    function M:stop() remove() end
    function M:sample(real)
        if real-self.last<.25 then return end;self.last=real
        local ok,err=pcall(function()
            local f=io.open(base..'guest-floor-'..session..'.txt','rb')
            local text=f and f:read(8193) or '';if f then f:close() end
            local values={};local valid=#text<=8192
            for k,v in text:gmatch('([%w_]+)=([^\r\n]+)') do if values[k] then valid=false end;values[k]=v end
            local expiry=tonumber(values.expires_at) or 0
            if not valid or values.Session~=session or values.source~='dl2-lab-floor' or values.units~='guest-centimetres' or
               values.seq~=values.end_seq or expiry<=os.time() or expiry>os.time()+3 then remove();return end
            local sequence=assert(tonumber(values.seq));assert(sequence>0)
            if self.component and api.valid(self.component) and sequence>=self.sequence then
                -- Identical static geometry is not recooked every packet.
                assert(values.geometry_id==self.geometry_id,'Geometry changed; recreate through a new session')
                return
            end
            assert(values.triangle_count=='2','Only the verified two-triangle lab floor is supported')
            local vertices={};local indices={}
            for i=0,1 do
                local numbers={}
                for token in assert(values['triangle_'..i]):gmatch('[^,]+') do
                    local value=assert(tonumber(token));assert(value==value and math.abs(value)<1e6,'Invalid collider vertex')
                    numbers[#numbers+1]=value
                end
                assert(#numbers==9,'Invalid triangle')
                for offset=1,9,3 do vertices[#vertices+1]={X=numbers[offset],Y=numbers[offset+1],Z=numbers[offset+2]} end
                local offset=i*3
                for _,index in ipairs({offset,offset+1,offset+2,offset+2,offset+1,offset}) do indices[#indices+1]=index end
            end
            local class=StaticFindObject('/Script/ProceduralMeshComponent.ProceduralMeshComponent')
            assert(api.valid(class),'Procedural mesh class unavailable')
            local saved=io.open(base..'guest-live-weapon-'..session..'.txt','rb')
            local expected=saved and saved:read('*a') or '';if saved then saved:close() end
            local weapon
            for _,candidate in ipairs(FindAllOf('BP_Weapon_Tool_Axe_C_C') or {}) do
                if api.valid(candidate) and api.safe_text(candidate)==expected then weapon=candidate;break end
            end
            assert(api.valid(weapon) and api.call(api.read(weapon,'RootComponent'),'GetCollisionObjectType')==14,'Current axe collision channel differs')
            local world=api.call(pawn,'GetWorld')
            self.actor=world:SpawnActor(StaticFindObject('/Script/Engine.Actor'),{X=0,Y=0,Z=0},{Pitch=0,Yaw=0,Roll=0})
            assert(api.valid(self.actor),'Collider actor unavailable')
            self.component=self.actor:AddComponentByClass(class,false,{Translation={X=0,Y=0,Z=0},Rotation={X=0,Y=0,Z=0,W=1},Scale3D={X=1,Y=1,Z=1}},false)
            assert(api.valid(self.component),'Collider component unavailable')
            self.actor:SetActorHiddenInGame(true);self.component:SetVisibility(false,false);self.component:SetHiddenInGame(true,false)
            self.component:SetCollisionEnabled(0);self.component:SetMobility(2)
            self.component.bUseComplexAsSimpleCollision=true;self.component.bUseAsyncCooking=true
            self.component:SetCollisionObjectType(0);self.component:SetCollisionResponseToAllChannels(0)
            self.component:SetCollisionResponseToChannel(14,2)
            self.component:CreateMeshSection(0,vertices,indices,{},{},{},{},true)
            assert(self.component:GetNumSections()==1,'Collider section missing')
            assert(self.component:GetCollisionResponseToChannel(14)==2 and self.component:GetCollisionResponseToChannel(16)==0 and self.component:GetCollisionResponseToChannel(2)==0,'Weapon-only collision mask mismatch')
            self.component:SetCollisionEnabled(3)
            self.physics=self.component:GetCollisionEnabled()==3;assert(self.physics,'Collider did not enable')
            self.sequence=sequence;self.geometry_id=values.geometry_id
            local a,b,c=vertices[1],vertices[2],vertices[3]
            local centre={X=(a.X+b.X+c.X)/3,Y=(a.Y+b.Y+c.Y)/3,Z=a.Z};self.trace_centre=centre
            local trace_ok,trace=pcall(function() return self.component:K2_LineTraceComponent({X=centre.X,Y=centre.Y,Z=centre.Z+50},{X=centre.X,Y=centre.Y,Z=centre.Z-50},true,false,false,{},{},{},{}) end)
            self.trace=trace_ok and trace or false
        end)
        if not ok then self.error=tostring(err):gsub('[\r\n=]',' '):sub(1,240);remove() end
        if ok and self.physics and not self.trace and self.trace_centre and self.trace_at~=os.time() then
            -- Async collision cooking can finish after the section is created.
            -- Retry the read-only component query at most once per second.
            self.trace_at=os.time();local centre=self.trace_centre
            local trace_ok,trace=pcall(function() return self.component:K2_LineTraceComponent({X=centre.X,Y=centre.Y,Z=centre.Z+50},{X=centre.X,Y=centre.Y,Z=centre.Z-50},true,false,false,{},{},{},{}) end)
            self.trace=trace_ok and trace or false
        end
        local status=io.open(base..'guest-floor-status-'..session..'.txt','wb')
        if status then status:write('physics='..(self.physics and '1' or '0')..'\nsequence='..self.sequence..'\ntrace_hit='..tostring(self.trace)..'\nerror='..self.error..'\n');status:close() end
    end
    return M
end
