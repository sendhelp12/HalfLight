-- Keep native animation/bone refresh running while the guest world is hidden.
return function(api,pawn,statics,session)
    local base=(HALFLIGHT_ROOT.."/work/lab/")
    local M={off=false,error='none',saved={},failed=false,npcs={}};local mesh=api.read(pawn,'Mesh')
    local keys={VisibilityBasedAnimTickOption=0,bEnableUpdateRateOptimizations=false}
    local function status()
        local body='Session='..session..'\nworld_rendering='..(M.off and 0 or 1)..'\nmesh_settings_restored='..((not M.off and #M.saved==0 and #M.npcs==0) and 1 or 0)..'\nnpc_ticks_suspended='..#M.npcs..'\nclothing_ticks_suspended=0\nbody_tick_enabled='..tostring(api.call(mesh,'IsComponentTickEnabled')==true)..'\nerror='..M.error..'\n'
        for key in pairs(keys) do local value=api.read(mesh,key);body=body..key..'='..tostring(value)..'\n' end
        if body~=M.last_status then
            local f=io.open(base..'guest-background-rendering-'..session..'.txt','wb')
            if f then local ok=f:write(body);f:close();if ok then M.last_status=body end end
        end
    end
    local function suspend_npcs()
        assert(type(FindAllOf)=='function','Source pawn inventory unavailable')
        local actors=FindAllOf('Willie_BP_C') or {};assert(#actors<=1024,'Too many source pawns')
        local world=api.safe_text(api.call(pawn,'GetWorld'));local mine=api.safe_text(pawn)
        local count=#actors
        for i=1,count do local actor=actors[i]
            if api.valid(actor) and api.safe_text(actor)~=mine and api.safe_text(api.call(actor,'GetWorld'))==world then
                local controller=api.call(actor,'GetController')
                if api.valid(controller) and api.call(controller,'IsPlayerController')==false then actors[#actors+1]=controller end
            end
        end
        local seen={};for _,entry in ipairs(M.npcs) do seen[api.safe_text(entry.actor)]=true end
        for _,actor in ipairs(actors) do if api.valid(actor) and api.safe_text(actor)~=mine and not seen[api.safe_text(actor)] and api.safe_text(api.call(actor,'GetWorld'))==world then
            local tick=api.call(actor,'IsActorTickEnabled');assert(type(tick)=='boolean','Source actor tick state unavailable')
            local entry={actor=actor,tick=tick,parts={}};M.npcs[#M.npcs+1]=entry
            seen[api.safe_text(actor)]=true;actor:SetActorTickEnabled(false)
            assert(api.call(actor,'IsActorTickEnabled')==false,'Source actor tick suspension did not apply')
            local parts=actor:K2_GetComponentsByClass(StaticFindObject('/Script/Engine.ActorComponent'))
            local function suspend(part)
                if not api.valid(part) then part=part:get() end
                if not api.valid(part) then return end
                local enabled=api.call(part,'IsComponentTickEnabled');assert(type(enabled)=='boolean','Source component tick state unavailable')
                entry.parts[#entry.parts+1]={part=part,tick=enabled};part:SetComponentTickEnabled(false)
                assert(api.call(part,'IsComponentTickEnabled')==false,'Source component tick suspension did not apply')
            end
            if type(parts)=='table' and not parts.ForEach then for _,part in pairs(parts) do suspend(part) end
            else parts:ForEach(function(_,wrapped) suspend(wrapped:get()) end) end
        end end
    end
    local function restore()
        if M.off then
            local context=api.valid(pawn) and pawn or (type(FindFirstOf)=='function' and FindFirstOf('PlayerController'))
            assert(api.valid(context),'Rendering restoration context unavailable');statics:SetEnableWorldRendering(context,true);M.off=false
        end
        for _,entry in ipairs(M.saved) do if api.valid(entry.mesh) then
            for key,value in pairs(entry.values) do entry.mesh[key]=value;assert(api.read(entry.mesh,key)==value,'Mesh restoration did not apply: '..key) end
            entry.mesh:SetComponentTickEnabled(entry.tick)
            assert(api.call(entry.mesh,'IsComponentTickEnabled')==entry.tick,'Mesh tick restoration did not apply')
        end end
        M.saved={}
        for _,entry in ipairs(M.npcs) do
            for _,component in ipairs(entry.parts) do if api.valid(component.part) then
                component.part:SetComponentTickEnabled(component.tick)
                assert(api.call(component.part,'IsComponentTickEnabled')==component.tick,'Source component tick restoration did not apply')
            end end
            if api.valid(entry.actor) then entry.actor:SetActorTickEnabled(entry.tick);assert(api.call(entry.actor,'IsActorTickEnabled')==entry.tick,'Source actor tick restoration did not apply') end
        end
        M.npcs={};M.last_npcs=nil
    end
    function M:stop()
        local ok,err=pcall(restore)
        if not ok then self.error=tostring(err):gsub('[\r\n=]',' '):sub(1,200) end
        status()
    end
    function M:sample(active)
        local f=io.open(base..'guest-rendering-required.ini','rb');local text=f and f:read(1025) or '';if f then f:close() end
        local requested=#text<=1024 and text:match('BackgroundRendering=(%d+)')=='0' and active==true
        if not requested or self.failed then self:stop();return end
        if api.read(pawn,'Fallen')==true or api.read(pawn,'Ded')==true then
            self.error='Waiting for a standing, alive character';self.waiting_for_stance=true;self.standing_since=nil;self:stop();return
        end
        if self.waiting_for_stance then
            self.standing_since=self.standing_since or os.clock()
            if os.clock()-self.standing_since<1 then self:stop();return end
            self.waiting_for_stance=false;self.error='none'
        end
        if self.off then
            if not self.last_npcs or os.clock()-self.last_npcs>=2 then
                self.last_npcs=os.clock();local ok,err=pcall(suspend_npcs)
                if not ok then self.error=tostring(err);self.failed=true;self:stop() else status() end
            end
            return
        end
        local ok,err=pcall(function()
            assert(api.valid(mesh),'Native character mesh missing')
            local parts=pawn:K2_GetComponentsByClass(StaticFindObject('/Script/Engine.SkeletalMeshComponent'))
            local seen={}
            local function prepare(part)
                if not api.valid(part) then part=part:get() end
                if not api.valid(part) or seen[api.safe_text(part)] then return end;seen[api.safe_text(part)]=true
                local values={}
                for key,wanted in pairs(keys) do
                    local value=api.read(part,key)
                    assert(type(value)==type(wanted),'Animation setting unavailable: '..key);values[key]=value
                end
                local tick=api.call(part,'IsComponentTickEnabled');assert(type(tick)=='boolean','Mesh tick state unavailable')
                self.saved[#self.saved+1]={mesh=part,values=values,tick=tick}
                -- Player mesh components can drive linked animation and physics;
                -- world rendering being off must not stop those dependencies.
                for key,value in pairs(keys) do part[key]=value;assert(api.read(part,key)==value,'Animation setting did not apply: '..key) end
                part:SetComponentTickEnabled(true)
                assert(api.call(part,'IsComponentTickEnabled')==true,'Source mesh tick policy did not apply')
            end
            prepare(mesh)
            if type(parts)=='table' and not parts.ForEach then for _,part in pairs(parts) do prepare(part) end
            else parts:ForEach(function(_,wrapped) prepare(wrapped:get()) end) end
            assert(api.read(pawn,'Fallen')~=true and api.read(pawn,'Ded')~=true,'Start rendering-off mode while standing and alive')
            statics:SetEnableWorldRendering(pawn,false);self.off=true
            suspend_npcs();self.last_npcs=os.clock()
        end)
        if not ok then self.error=tostring(err):gsub('[\r\n=]',' '):sub(1,200);self.failed=true;self:stop() else status() end
    end
    status()
    return M
end
