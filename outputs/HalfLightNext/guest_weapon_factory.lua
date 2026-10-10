-- Construct owned native passport data; class pointers never enter Lua struct marshalling.
return function(api,pawn)
    local recipes=assert(loadfile((HALFLIGHT_ROOT.."/work/lab/catalog-recipes.lua")))()
    return function(profile)
        local path=assert(profile.path or profile.source_class_path)
        assert(path:match('^/Game/Assets/Weapons/Blueprints/[A-Za-z0-9_/]+$'),'Invalid native weapon path')
        LoadAsset(path)
        local class=StaticFindObject(path..'.'..path:match('([^/]+)$')..'_C');assert(api.valid(class),'Native weapon class unavailable')
        local world=assert(api.call(pawn,'GetWorld'))
        local seed=world:SpawnActor(class,api.call(pawn,'K2_GetActorLocation'),{Pitch=0,Yaw=0,Roll=0})
        assert(api.valid(seed),'Native weapon construction failed')
        local ok,passport=pcall(function()
            local data=assert(api.read(seed,'Weapon Passport'))
            if profile.recipe then
                for key,value in pairs(assert(recipes[profile.recipe],'Unknown native assembly')) do
                    if type(value)=='table' and value.object then
                        local module=value.object;assert(module:match('^/Game/[A-Za-z0-9_/]+%.[A-Za-z0-9_]+_C$'),'Invalid native module')
                        LoadAsset(module:match('^(.-)%.'));local object=StaticFindObject(module)
                        assert(api.valid(object),'Native module unavailable');data[key]=object
                    elseif type(value)=='table' then
                        local nested=assert(api.read(data,key));for field,n in pairs(value) do assert(type(n)=='number');nested[field]=n end
                    elseif type(value)=='string' then data[key]=FName(value)
                    else data[key]=value end
                end
            end
            data["WeaponClass_54_B478ECF7499977809745A3973AD678EC"]=class
            return data
        end)
        if not ok then seed:K2_DestroyActor();error(passport) end
        return class,passport,seed
    end
end
