-- Resolve the selected source weapon in either native hand slot.
return function(api,pawn)
    local registry=assert(loadfile(HALFLIGHT_ROOT..'/outputs/HalfLightNext/guest_weapon_catalog.lua'))()(api)
    return function(requested)
        for _,side in ipairs({'R','L'}) do
            if not requested or requested==side then
            local weapon=api.read(pawn,'Weapon '..side)
            if api.valid(weapon) then
                if registry:class_supported(weapon) then return weapon,side end
            end
            end
        end
    end
end
