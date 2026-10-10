-- Explicit menu requests use native spawn/setup; no Windows input injection.
return function(api,pawn,session)
    local base=(HALFLIGHT_ROOT.."/work/lab/")
    local registry=assert(loadfile((HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_weapon_catalog.lua")))()(api)
    local factory
    local M={sequence=0,last=-1,error='none',state='ready',removed=0};local templates={};local tracked={};local dormant={};local setups={R='Set Up Right Hand Weapon',L='Set Up Left Hand Weapon'}
    local class=assert(api.call(pawn,'GetClass'));local found={}
    class:ForEachFunction(function(fn)
        local name=fn:GetFName():ToString()
        for side,expected in pairs(setups) do if name==expected then
            local properties={};fn:ForEachProperty(function(p) if #properties<5 then properties[#properties+1]=p:GetFullName() end end)
            local kinds={'ClassProperty','ObjectProperty','BoolProperty','BoolProperty','StructProperty'}
            for i,kind in ipairs(kinds) do assert(properties[i] and properties[i]:sub(1,#kind+1)==kind..' ','Native equip signature changed: '..name) end
            found[side]=true
        end end
    end)
    assert(found.R and found.L,'Native hand setup unavailable')
    local function remember(weapon)
        local index,p=registry:match(weapon)
        if index and api.read(weapon,'Weapon Passport')~=nil and not dormant[api.safe_text(templates[p.id])] then templates[p.id]=weapon end
    end
    for _,side in ipairs({'R','L'}) do remember(api.read(pawn,'Weapon '..side)) end
    local function current(side)
        local _,p=registry:match(api.read(pawn,'Weapon '..side));return p and p.id or 'none'
    end
    local function publish(path,body)
        local f=io.open(path,'wb');if not f then return false end
        local ok=pcall(function() assert(f:write(body)) end);f:close();return ok
    end
    local function cleanup(real)
        if M.last_cleanup and real-M.last_cleanup<2 then return end;M.last_cleanup=real
        local ok,err=pcall(function()
            assert(type(FindAllOf)=='function','Weapon cleanup inventory unavailable')
            local protected={};local slots={'Weapon R','Weapon L','Weapon Slot R 1','Weapon Slot R 2','Weapon Slot L 1','Weapon Slot L 2','Weapon Slot Back'}
            local pawn_name=api.safe_text(pawn)
            local pawns=FindAllOf('Willie_BP_C') or {};assert(#pawns<=1024,'Too many pawns for weapon cleanup')
            pawns[#pawns+1]=pawn
            for _,holder in ipairs(pawns) do if api.valid(holder) then
                local mine=api.safe_text(holder)==pawn_name
                for _,slot in ipairs(slots) do local actor=api.read(holder,slot)
                    if api.valid(actor) then
                        local name=api.safe_text(actor);protected[name]=true
                        if mine then tracked[name]=actor;remember(actor) end
                    end
                end
            end end
            local actors_to_check={}
            -- Rediscover old owned drops once on attachment; subsequent cleanup
            -- follows equipped identities rather than rescanning every class.
            if not M.discovered then
                local classes={Weapon_Fists_C=true};for _,p in ipairs(registry.profiles) do classes[p.class]=true end
                for class_name in pairs(classes) do
                    local actors=FindAllOf(class_name) or {};assert(#actors<=1024,'Too many actors for weapon cleanup')
                    for _,actor in ipairs(actors) do if api.valid(actor) then actors_to_check[api.safe_text(actor)]=actor end end
                end
                M.discovered=true
            end
            for name,actor in pairs(tracked) do actors_to_check[name]=actor end
            local world=api.safe_text(api.call(pawn,'GetWorld'));local candidates={}
            for _,actor in pairs(actors_to_check) do if api.valid(actor) then
                    local name=api.safe_text(actor)
                    local owner=api.read(actor,'Parent Actor');local engine_owner=api.call(actor,'GetOwner')
                    local owner_name,engine_owner_name=api.safe_text(owner),api.safe_text(engine_owner)
                    local mine=tracked[name]~=nil or owner_name==pawn_name or engine_owner_name==pawn_name
                    local foreign=(api.valid(owner) and owner_name~=pawn_name) or (api.valid(engine_owner) and engine_owner_name~=pawn_name)
                    if mine and not foreign and not protected[name] and api.safe_text(api.call(actor,'GetWorld'))==world and not api.valid(api.call(actor,'GetAttachParentActor')) then
                        local _,p=registry:match(actor)
                        if p or name:match('^Weapon_Fists_C ') then candidates[#candidates+1]={actor=actor,profile=p};tracked[name]=actor end
                    end
            end end
            -- ponytail: keep at most one inert assembly template per catalog type;
            -- remove at most eight actors per two seconds to avoid a destruction burst.
            local removed=0
            for _,entry in ipairs(candidates) do local actor,p=entry.actor,entry.profile;local name=api.safe_text(actor)
                if p and not api.valid(templates[p.id]) then templates[p.id]=actor end
                if p and api.safe_text(templates[p.id])==name then
                    if not dormant[name] then
                        local parts=actor:K2_GetComponentsByClass(StaticFindObject('/Script/Engine.PrimitiveComponent'))
                        local function freeze(part)
                            if not api.valid(part) then part=part:get() end
                            if api.valid(part) then
                                part:SetSimulatePhysics(false);part:SetCollisionEnabled(0);part:SetComponentTickEnabled(false)
                                assert(api.call(part,'IsAnySimulatingPhysics')==false and api.call(part,'GetCollisionEnabled')==0,'Template physics did not stop')
                            end
                        end
                        if type(parts)=='table' and not parts.ForEach then for _,part in pairs(parts) do freeze(part) end
                        else parts:ForEach(function(_,wrapped) freeze(wrapped:get()) end) end
                        actor:SetActorEnableCollision(false);actor:SetActorTickEnabled(false);actor:SetActorHiddenInGame(true);dormant[name]=actor
                    end
                elseif removed<8 then
                    actor:K2_DestroyActor();tracked[name]=nil;dormant[name]=nil;removed=removed+1;M.removed=M.removed+1
                end
            end
            for name,actor in pairs(tracked) do if not api.valid(actor) then tracked[name]=nil end end
            for name,actor in pairs(dormant) do if not api.valid(actor) then dormant[name]=nil end end
            M.cleanup_candidates=#candidates;M.cleanup_dormant=0;for _ in pairs(dormant) do M.cleanup_dormant=M.cleanup_dormant+1 end
            M.cleanup_templates={};for id,actor in pairs(templates) do
                M.cleanup_templates[#M.cleanup_templates+1]='template_'..id..'='..api.safe_text(actor)..'|protected:'..tostring(protected[api.safe_text(actor)]==true)..'|dormant:'..tostring(dormant[api.safe_text(actor)]~=nil)
            end
        end)
        local body='Session='..session..'\nremoved_total='..M.removed..'\ndormant_templates='..(M.cleanup_dormant or 0)..'\ncandidates='..(M.cleanup_candidates or 0)..'\nerror='..(ok and 'none' or tostring(err):gsub('[\r\n=]',' '):sub(1,200))..'\n'..table.concat(M.cleanup_templates or {},'\n')..'\n'
        if body~=M.last_cleanup_status then
            if publish(base..'weapon-cleanup-'..session..'.txt',body) then M.last_cleanup_status=body end
        end
    end
    local function status(state,error)
        M.state=state
        local body='Session='..session..'\nrequest_sequence='..M.sequence..'\nstate='..state..'\nright='..current('R')..'\nleft='..current('L')..'\nempty_available='..tostring(M.empty_available==true)..'\nerror='..tostring(error or 'none'):gsub('[\r\n=]',' '):sub(1,200)..'\n'
        if body==M.last_status then return end
        if publish(base..'weapon-menu-status-'..session..'.txt',body) then M.last_status=body end
    end
    local function resolve(id)
        if id=='none' then
            local world=api.safe_text(api.call(pawn,'GetWorld'))
            local actors=type(FindAllOf)=='function' and FindAllOf('Weapon_Fists_C') or {}
            assert(#actors<=1024,'Too many empty-hand template actors')
            for _,actor in ipairs(actors) do
                if api.valid(actor) and api.safe_text(actor):match('^Weapon_Fists_C ') and api.safe_text(api.call(actor,'GetWorld'))==world then
                    local passport=api.read(actor,'Weapon Passport');local c=api.call(actor,'GetClass')
                    if passport~=nil and api.valid(c) then return c,passport end
                end
            end
            local default=StaticFindObject('/Game/Assets/Weapons/Blueprints/Built_Weapons/Weapon_Fists.Default__Weapon_Fists_C')
            if api.valid(default) and api.safe_text(default):match('^Weapon_Fists_C ') then
                local passport=api.read(default,'Weapon Passport');local c=api.call(default,'GetClass')
                if passport~=nil and api.valid(c) then return c,passport end
            end
            error('Native empty-hand template unavailable in this match')
        end
        local profile;for _,p in ipairs(registry.profiles) do if p.id==id then profile=p end end
        assert(profile,'Unknown weapon selection')
        if profile.path then
            if not factory then factory=assert(loadfile((HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_weapon_factory.lua")))()(api,pawn) end
            return factory(profile)
        end
        if not api.valid(templates[id]) and type(FindAllOf)=='function' then
            local actors=FindAllOf(profile.class) or {};assert(#actors<=1024,'Too many template actors')
            local world=api.call(pawn,'GetWorld')
            for _,actor in ipairs(actors) do
                if api.valid(actor) and api.safe_text(api.call(actor,'GetWorld'))==api.safe_text(world) then remember(actor) end
                if api.valid(templates[id]) then break end
            end
        end
        local actor=templates[id]
        assert(api.valid(actor),'Load this weapon in Half Sword once to register its assembly: '..id)
        local _,actual=registry:match(actor);assert(actual and actual.id==id,'Template assembly changed')
        local passport=assert(api.read(actor,'Weapon Passport'),'Weapon passport missing')
        local weapon_class=assert(api.call(actor,'GetClass'),'Weapon class missing')
        assert(api.valid(weapon_class),'Invalid weapon class')
        return weapon_class,passport
    end
    M.empty_available=pcall(resolve,'none')
    status('ready')
    function M:sample(real)
        for _,side in ipairs({'R','L'}) do local actor=api.read(pawn,'Weapon '..side)
            if api.valid(actor) then tracked[api.safe_text(actor)]=actor end
        end
        if real-self.last<.1 then return end;self.last=real
        cleanup(real)
        status(self.state,self.error)
        local f=io.open(base..'weapon-menu-request-'..session..'.txt','rb');if not f then return end
        local text=f:read(1025);f:close();if not text or #text>1024 then return end
        local v={};local count=0;local allowed={Session=true,seq=true,end_seq=true,expires_at=true,right=true,left=true}
        for line in text:gmatch('[^\r\n]+') do
            local key,value=line:match('^([^=]+)=([^=]+)$')
            if not key or not allowed[key] or v[key] then return end;v[key]=value;count=count+1
        end
        if count~=6 then return end
        local seq=tonumber(v.seq);local expiry=tonumber(v.expires_at)
        if v.Session~=session or not seq or seq%1~=0 or seq<=self.sequence or seq>1e12 or v.seq~=v.end_seq or not expiry or expiry<=os.time() or expiry>os.time()+30 then return end
        self.sequence=seq
        local previous={R=api.read(pawn,'Weapon R'),L=api.read(pawn,'Weapon L')};local changed={};local choices={}
        local ok,err=pcall(function()
            for _,weapon in pairs(previous) do remember(weapon);if api.valid(weapon) then tracked[api.safe_text(weapon)]=weapon end end
            choices.R={resolve(assert(v.right))};choices.L={resolve(assert(v.left))}
            status('applying')
            for _,side in ipairs({'R','L'}) do
                local choice=choices[side]
                changed[side]=true
                pawn[setups[side]](pawn,choice[1],nil,true,false,choice[2])
                local actor=api.read(pawn,'Weapon '..side)
                -- Preset construction replaces its passport defaults; native X reads this class.
                local passport=api.read(actor,'Weapon Passport');if passport then passport["WeaponClass_54_B478ECF7499977809745A3973AD678EC"]=choice[1] end
                local _,profile=registry:match(actor)
                local wanted=v[side=='R' and 'right' or 'left']
                assert((wanted=='none' and api.safe_text(actor):match('^Weapon_Fists_C ')) or (profile and profile.id==wanted),'Native equip did not produce the selected assembly in '..side)
            end
            assert(api.safe_text(api.read(pawn,'Weapon R'))~=api.safe_text(api.read(pawn,'Weapon L')),'Hands must hold independent weapon actors')
        end)
        for _,choice in pairs(choices) do if api.valid(choice[3]) then choice[3]:K2_DestroyActor() end end
        if not ok then
            for side in pairs(changed) do local actor=previous[side]
                if api.valid(actor) then pcall(function() pawn[setups[side]](pawn,nil,actor,true,false,api.read(actor,'Weapon Passport')) end) end
            end
            self.error=tostring(err);status('error',self.error)
        else self.error='none';status('applied') end
    end
    return M
end
