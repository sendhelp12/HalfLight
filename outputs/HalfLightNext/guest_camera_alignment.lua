-- Low-rate read-only camera/hand diagnostics alongside the continuous link.
return function(api,pawn,mesh,session)
    local controller=api.call(pawn,'GetController');assert(api.valid(controller),'Controller unavailable')
    local camera=api.read(controller,'PlayerCameraManager');assert(api.valid(camera),'Camera unavailable')
    local reflection={}
    for _,path in ipairs({'/Script/Engine.Controller:SetControlRotation','/Script/Engine.Controller:GetControlRotation','/Script/Engine.PlayerCameraManager:SetFOV'}) do
        local fn=StaticFindObject(path)
        if api.valid(fn) then
            local params={};fn:ForEachProperty(function(p) params[#params+1]=p:GetFullName() end)
            reflection[#reflection+1]=api.safe_text(fn)..'('..table.concat(params,',')..')'
        else reflection[#reflection+1]=path..'=missing' end
    end
    local reflected=assert(io.open((HALFLIGHT_ROOT.."/work/lab/guest-camera-control-reflection.txt"),'wb'));reflected:write(table.concat(reflection,'\n'));reflected:close()
    local hand
    for i=0,math.min(tonumber(api.call(mesh,'GetNumBones')) or 0,256)-1 do
        local bone=api.call(mesh,'GetBoneName',i)
        if tostring(api.call(bone,'ToString') or ''):lower()=='hand_r' then hand=bone;break end
    end
    assert(hand,'Actual right-hand bone missing')
    local path=(HALFLIGHT_ROOT.."/work/lab/guest-camera-alignment-")..session..'.txt'
    local M={last=-1,error='none'}
    function M:sample(real)
        if real-self.last<.2 then return end;self.last=real
        local values={'Session='..session,'unix_seconds='..os.time(),'real_seconds='..real}
        for _,item in ipairs({{camera,'GetCameraLocation',{'X','Y','Z'},'camera_'},{camera,'GetCameraRotation',{'Pitch','Yaw','Roll'},'camera_'},{controller,'GetControlRotation',{'Pitch','Yaw','Roll'},'control_'},{mesh,'GetSocketLocation',{'X','Y','Z'},'hand_',hand}}) do
            local result=api.call(item[1],item[2],item[5])
            for _,axis in ipairs(item[3]) do
                local value=tonumber(api.read(result,axis));assert(value and value==value and math.abs(value)<1e6,'Invalid camera/hand observation')
                values[#values+1]=item[4]..axis:lower()..'='..value
            end
        end
        local ok,fov=pcall(function() return tonumber(api.call(camera,'GetFOVAngle')) end)
        if ok and fov then values[#values+1]='camera_fov='..fov end
        local file=assert(io.open(path,'wb'));file:write(table.concat(values,'\n')..'\n');file:close()
    end
    return M
end
