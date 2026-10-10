-- One registry shared by source binding, hand packets and menu equipping.
return function(api)
    local f=assert(io.open((HALFLIGHT_ROOT.."/.local/catalog.ini"),'rb'),'Weapon catalog missing')
    local text=f:read(262145);f:close();assert(#text<=262144,'Catalog too large')
    local values={};for key,value in text:gmatch('([^=\r\n]+)=([^\r\n]+)') do assert(not values[key],'Duplicate catalog field');values[key]=value end
    local count=tonumber(values.Count);assert(values.Version=='1' and count and count%1==0 and count>=1 and count<=32,'Invalid catalog version/count')
    local M={profiles={},count=count};local cache={}
    for i=0,count-1 do
        local prefix='Weapon.'..i..'.';local p={id=values[prefix..'Id'],class=values[prefix..'Class'],component=values[prefix..'Component'],parts={},scale={},part_scales={},path=values[prefix..'Path'],recipe=values[prefix..'Recipe'],offset=tonumber(values[prefix..'Offset']) or 0}
        assert(p.offset>=0 and p.offset<=30,'Invalid catalog pose offset')
        assert(p.id and p.id:match('^[a-z][a-z0-9_]*$') and p.class and p.component,'Catalog profile missing')
        for v in assert(values[prefix..'Scale']):gmatch('[^,]+') do local n=assert(tonumber(v));assert(n>=.05 and n<=10);p.scale[#p.scale+1]=n end
        assert(#p.scale==3)
        for key,value in pairs(values) do if key:sub(1,#prefix+5)==prefix..'Part.' then p.parts[key:sub(#prefix+6)]=value end end
        for label in pairs(p.parts) do
            local text=values[prefix..'PartScale.'..label]
            if text then local scale={};for v in text:gmatch('[^,]+') do local n=assert(tonumber(v));assert(n>=.05 and n<=10);scale[#scale+1]=n end;assert(#scale==3);p.part_scales[label]=scale end
        end
        assert(p.parts[p.component],'Pose component not verified');M.profiles[i+1]=p
    end
    function M:class_supported(weapon)
        local name=api.safe_text(weapon)
        for _,p in ipairs(self.profiles) do if name:sub(1,#p.class+1)==p.class..' ' then return true end end
        return false
    end
    function M:match(weapon)
        if not api.valid(weapon) then return end
        local name=api.safe_text(weapon);local saved=cache[name]
        if saved then if saved.index then return saved.index,saved.profile,saved.component end;return end
        local candidates={};for i,p in ipairs(self.profiles) do if name:sub(1,#p.class+1)==p.class..' ' then candidates[#candidates+1]={i-1,p} end end
        if #candidates==0 then cache[name]={};return end
        local parts=weapon:K2_GetComponentsByClass(StaticFindObject('/Script/Engine.SceneComponent'));local components={}
        local function inspect(part)
            if not api.valid(part) then part=part:get() end
            if api.valid(part) then components[api.safe_text(part):match('%.([^%.]+)$') or '']=part end
        end
        if type(parts)=='table' and not parts.ForEach then for _,part in pairs(parts) do inspect(part) end
        else parts:ForEach(function(_,wrapped) inspect(wrapped:get()) end) end
        for _,candidate in ipairs(candidates) do
            local index,p=candidate[1],candidate[2];local good=true
            for label,asset in pairs(p.parts) do
                local part=components[label];local mesh=api.valid(part) and api.read(part,'StaticMesh') or nil
                good=good and api.valid(mesh) and api.safe_text(mesh)=='StaticMesh '..asset
                local expected=p.part_scales[label]
                if good and expected then local scale=api.read(part,'RelativeScale3D');for i,axis in ipairs({'X','Y','Z'}) do local n=tonumber(api.read(scale,axis));good=good and n~=nil and math.abs(n-expected[i])<.001 end end
            end
            if good then saved={index=index,profile=p,component=components[p.component]};cache[name]=saved;return index,p,saved.component end
        end
        cache[name]={}
    end
    return M
end
