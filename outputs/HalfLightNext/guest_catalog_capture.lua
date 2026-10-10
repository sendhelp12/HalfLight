-- Bounded native assembly import on the existing match/game-thread scheduler.
-- Explicit file request only; no Windows input and no active forwarding.
return function(api,pawn)
    local base=(HALFLIGHT_ROOT.."/work/lab/")
    local M={last=0};local setups={R='Set Up Right Hand Weapon',L='Set Up Left Hand Weapon'}
    local palm=assert(loadfile(HALFLIGHT_ROOT..'/outputs/HalfLightNext/guest_palm_frame.lua'))()
    local function vector(value,axes)
        local out={};for _,axis in ipairs(axes) do
            local n=tonumber(api.read(value,axis));assert(n and n==n and math.abs(n)<1e20,'Invalid capture transform '..axis..'='..tostring(api.read(value,axis)))
            out[#out+1]=string.format('%.12g',n)
        end;return table.concat(out,',')
    end
    local function transform(part)
        local t=assert(api.call(part,'K2_GetComponentToWorld'))
        return vector(api.read(t,'Translation'),{'X','Y','Z'})..','..vector(api.read(t,'Rotation'),{'X','Y','Z','W'})..','..vector(api.read(t,'Scale3D'),{'X','Y','Z'})
    end
    local function restore()
        if M.previous and api.valid(pawn) then for _,side in ipairs({'R','L'}) do
            local saved=M.previous[side];local actor=saved.actor
            pawn[setups[side]](pawn,api.valid(actor) and nil or saved.class,api.valid(actor) and actor or nil,true,false,saved.passport)
        end end
        M.previous=nil
    end
    function M:stop() pcall(restore) end
    local function write(state,error,lines)
        local f=assert(io.open(base..'catalog-capture-'..M.nonce..'.txt','wb'))
        f:write('Session='..M.nonce..'\nstate='..state..'\nindex='..M.index..'\nerror='..tostring(error or 'none'):gsub('[\r\n]',' ')..'\n'..table.concat(lines or {},'\n'));f:close()
    end
    function M:sample(real,forwarding)
        if forwarding then self:stop();return end
        if self.pending then
            if os.time()>self.expiry then self:stop();self.pending=nil;write('error','Capture request expired');return end
            if real-self.spawned<.4 then return end
            local ok,err=pcall(function()
                local actor=api.read(pawn,'Weapon '..self.side);assert(api.valid(actor),'Native spawn did not equip a weapon')
                assert(api.safe_text(actor):match('^'..self.class_name..' '),'Native spawn class differs')
                local root=api.read(actor,'RootComponent')
                local root_mesh=api.read(root,'StaticMesh')
                if api.safe_text(root_mesh):find('SM_Grip_Dummy',1,true) and api.valid(api.read(actor,'Head')) then root=api.read(actor,'Head') end
                assert(api.valid(root),'Native weapon pose component missing')
                local lines={'actor='..api.safe_text(actor),'root='..api.safe_text(root),'root_transform='..transform(root)}
                if self.calibrate then lines[#lines+1]='palm='..table.concat(assert(palm(api,pawn,root,self.side:lower(),0),'Weapon frame unavailable during palm capture'),',') end
                local passport=assert(api.read(actor,'Weapon Passport'))
                for key in (self.fields or ''):gmatch('[^,]+') do
                    assert(key:match('^[A-Za-z0-9_]+$'),'Invalid passport field')
                    local value=api.read(passport,key);local kind=type(value);local encoded
                    if value==nil then kind='nil';encoded='none'
                    elseif kind=='number' or kind=='boolean' or kind=='string' then encoded=tostring(value):gsub('[\r\n|]',' ')
                    elseif api.valid(value) then kind='object';encoded=api.safe_text(value)
                    elseif tonumber(api.read(value,'X')) then kind='vector';encoded=vector(value,{'X','Y','Z'})
                    elseif tonumber(api.read(value,'R')) then kind='color';encoded=vector(value,{'R','G','B','A'})
                    else kind='string';encoded=tostring(api.call(value,'ToString') or value):gsub('[\r\n|]',' ') end
                    lines[#lines+1]='passport='..key..'|'..kind..'|'..encoded
                end
                for _,k in ipairs({'Grip R Hand Default','Grip L Hand Default','Grip Alternative','OffhandLimit','OffhandStr','Edge Sharpness','Rigidity'}) do
                    lines[#lines+1]='property='..k..'|'..tostring(api.read(actor,k))
                end
                local parts=actor:K2_GetComponentsByClass(StaticFindObject('/Script/Engine.SceneComponent'));local visible_parts=0
                local function inspect(part)
                    if not api.valid(part) then part=part:get() end
                    if not api.valid(part) then return end
                    local mesh=api.read(part,'StaticMesh')
                    if api.valid(mesh) then
                        if not api.safe_text(mesh):find('SM_Grip_Dummy',1,true) then visible_parts=visible_parts+1 end
                        lines[#lines+1]='part='..api.safe_text(part)..'|asset='..api.safe_text(mesh)..'|parent='..api.safe_text(api.call(part,'GetAttachParent'))..'|transform='..transform(part)..'|hidden='..tostring(api.read(part,'bHiddenInGame'))..'|visible='..tostring(api.read(part,'bVisible'))
                    end
                    if api.safe_text(part):find('Grip ',1,true) then lines[#lines+1]='grip='..api.safe_text(part)..'|transform='..transform(part) end
                end
                if type(parts)=='table' and not parts.ForEach then for _,part in pairs(parts) do inspect(part) end
                else parts:ForEach(function(_,wrapped) inspect(wrapped:get()) end) end
                assert(visible_parts>0,'Native assembly has only a dummy pivot')
                -- Keep one inert native passport/assembly template for later menu equips.
                restore()
                if self.keep then pawn[setups[self.side]](pawn,api.call(actor,'GetClass'),nil,true,false,api.read(actor,'Weapon Passport')) end
                local primitives=actor:K2_GetComponentsByClass(StaticFindObject('/Script/Engine.PrimitiveComponent'))
                local function freeze(part)
                    if not api.valid(part) then part=part:get() end
                    if api.valid(part) then part:SetSimulatePhysics(false);part:SetCollisionEnabled(0);part:SetComponentTickEnabled(false) end
                end
                if type(primitives)=='table' and not primitives.ForEach then for _,part in pairs(primitives) do freeze(part) end
                else primitives:ForEach(function(_,wrapped) freeze(wrapped:get()) end) end
                actor:SetActorEnableCollision(false);actor:SetActorTickEnabled(false);actor:SetActorHiddenInGame(true)
                write('captured',nil,lines)
            end)
            self.pending=nil
            if not ok then self:stop();write('error',err) end
            return
        end
        if real-self.last<.1 then return end;self.last=real
        local file=io.open(base..'catalog-capture-request.ini','rb');if not file then return end
        local text=file:read(4097) or '';file:close();if #text>4096 then return end
        local v={};for k,value in text:gmatch('([^=\r\n]+)=([^\r\n]+)') do if v[k] then return end;v[k]=value end
        local expiry=tonumber(v.ExpiresUnix);local index=tonumber(v.Index)
        if not v.Session or not v.Session:match('^[0-9a-f]+$') or #v.Session~=16 or not index or index%1~=0 or index<1 or index>128 or not expiry or expiry<=os.time() or expiry>os.time()+30 then return end
        local token=v.Session..':'..index;if self.token==token then return end;self.token=token
        self.nonce=v.Session;self.index=index;self.expiry=expiry;self.fields=v.Fields;self.keep=v.KeepEquipped=='1'
        self.side=v.Side or 'R';self.calibrate=v.Calibrate=='1'
        local ok,err=pcall(function()
            assert(self.side=='R' or self.side=='L','Invalid capture hand')
            assert(v.ClassPath and (v.ClassPath:match('^/Game/Assets/Weapons/Blueprints/Built_Weapons/[A-Za-z0-9_/]+$') or v.ClassPath=='/Game/Assets/Weapons/Blueprints/ModularWeaponBP'),'Unapproved preset path')
            self.class_name=v.ClassPath:match('([^/]+)$')..'_C'
            LoadAsset(v.ClassPath)
            local class=StaticFindObject(v.ClassPath..'.'..self.class_name);assert(api.valid(class),'Native preset class unavailable')
            local default=StaticFindObject(v.ClassPath..'.Default__'..self.class_name);assert(api.valid(default),'Native preset default unavailable')
            local passport=assert(api.read(default,'Weapon Passport'),'Native preset passport unavailable')
            -- Forge data is written into an owned native struct, never marshalled
            -- as a Lua table containing class pointers.
            local recipe
            if v.Recipe then
                assert(v.ClassPath=='/Game/Assets/Weapons/Blueprints/ModularWeaponBP','Recipe class mismatch')
                local recipes=assert(loadfile(base..'catalog-recipes.lua'))()
                recipe=assert(recipes[v.Recipe],'Unknown distinct assembly')
            end
            local previous={}
            for _,side in ipairs({'R','L'}) do
                local original=api.read(pawn,'Weapon '..side);local template=original
                if not api.valid(template) then
                    LoadAsset('/Game/Assets/Weapons/Blueprints/Built_Weapons/Weapon_Fists')
                    template=StaticFindObject('/Game/Assets/Weapons/Blueprints/Built_Weapons/Weapon_Fists.Default__Weapon_Fists_C')
                end
                assert(api.valid(template),'Original or empty-hand template required for restoration')
                previous[side]={actor=original,class=assert(api.call(template,'GetClass')),passport=assert(api.read(template,'Weapon Passport'))}
            end
            self.previous=previous
            -- Use the existing native world spawner so preset BeginPlay can
            -- initialize modular data before the hand setup copies its passport.
            local world=assert(api.call(pawn,'GetWorld'));local location=api.call(pawn,'K2_GetActorLocation')
            local actor=world:SpawnActor(class,location,{Pitch=0,Yaw=0,Roll=0})
            assert(api.valid(actor),'Native preset world spawn failed')
            passport=assert(api.read(actor,'Weapon Passport'))
            if recipe then
                for key,value in pairs(recipe) do
                    if type(value)=='table' and value.object then
                        local path=value.object;assert(path:match('^/Game/[A-Za-z0-9_/]+%.[A-Za-z0-9_]+_C$'),'Invalid module path')
                        LoadAsset(path:match('^(.-)%.'));local object=StaticFindObject(path)
                        assert(api.valid(object),'Native module unavailable: '..path);passport[key]=object
                    elseif type(value)=='table' then
                        local nested=assert(api.read(passport,key));for field,n in pairs(value) do assert(type(n)=='number');nested[field]=n end
                    elseif type(value)=='string' then passport[key]=FName(value)
                    else passport[key]=value end
                end
                local seed=actor
                pawn[setups[self.side]](pawn,class,nil,true,false,passport)
                actor=assert(api.read(pawn,'Weapon '..self.side));assert(api.valid(actor),'Native recipe equip failed')
                seed:K2_DestroyActor()
            else pawn[setups[self.side]](pawn,nil,actor,true,false,passport) end
            local f=io.open(base..'catalog-debug-'..self.nonce..'.txt','wb');f:write(api.safe_text(actor));f:close()
            local meshes=actor:K2_GetComponentsByClass(StaticFindObject('/Script/Engine.StaticMeshComponent'));local count=0
            local function count_mesh(part)
                if not api.valid(part) then part=part:get() end
                local mesh=api.read(part,'StaticMesh');if api.valid(mesh) and not api.safe_text(mesh):find('SM_Grip_Dummy',1,true) then count=count+1 end
            end
            if type(meshes)=='table' and not meshes.ForEach then for _,part in pairs(meshes) do count_mesh(part) end
            else meshes:ForEach(function(_,wrapped) count_mesh(wrapped:get()) end) end
            if count==0 then
                assert(type(api.read(actor,'Initial Spawn'))=='boolean','Native modular initialization flag missing')
                actor['Initial Spawn']=true
                actor['ReSpawn Weapon Parts Event'](actor)
            end
            self.pending=true;self.spawned=real;write('spawning')
        end)
        if not ok then self:stop();write('error',err) end
    end
    return M
end
