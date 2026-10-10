-- Leased host look direction, applied through the verified Controller API.
return function(api,pawn,session)
    local controller=api.call(pawn,'GetController');assert(api.valid(controller),'Controller missing')
    local camera=api.read(controller,'PlayerCameraManager');assert(api.valid(camera),'Camera missing')
    local fn=StaticFindObject('/Script/Engine.Controller:SetControlRotation');assert(api.valid(fn),'Control-rotation function missing')
    local params={};fn:ForEachProperty(function(p) params[#params+1]=p:GetFullName() end)
    assert(#params==1 and params[1]=='StructProperty /Script/Engine.Controller:SetControlRotation:NewRotation','Unexpected control-rotation signature')
    local function signature(path,expected)
        local f=StaticFindObject(path);if not api.valid(f) then return false end
        local fields={};f:ForEachProperty(function(p) fields[#fields+1]=p:GetFullName() end)
        if #fields~=#expected then return false end
        for i,v in ipairs(expected) do if fields[i]~=v then return false end end
        return true
    end
    local manager_fov=signature('/Script/Engine.PlayerCameraManager:SetFOV',{'FloatProperty /Script/Engine.PlayerCameraManager:SetFOV:NewFOV'})
    local unlock_fov=signature('/Script/Engine.PlayerCameraManager:UnlockFOV',{})
    local controller_fov=signature('/Script/Engine.PlayerController:FOV',{'FloatProperty /Script/Engine.PlayerController:FOV:NewFOV'})
    local can_fov=(manager_fov and unlock_fov) or controller_fov
    local function angles(value)
        local result={}
        for _,k in ipairs({'Pitch','Yaw','Roll'}) do local n=tonumber(api.read(value,k));assert(n and n==n and math.abs(n)<1e6,'Invalid rotation');result[k]=n end
        return result
    end
    local initial=angles(api.call(controller,'GetControlRotation'));local initial_fov=tonumber(api.call(camera,'GetFOVAngle'))
    local base=(HALFLIGHT_ROOT.."/work/lab/")
    local packets=assert(loadfile((HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_packet_reader.lua")))()(base..'host-camera-follow-'..session..'.txt',4096)
    local M={last=-1,sequence=0,changed=false,calls=0,error='none',can_fov=can_fov,expiry=0}
    local timed=api.timed or function(_,fn) fn() end
    local function wrap(v)return (v+180)%360-180 end
    function M:close() packets:close() end
    function M:stop()
        if self.changed and api.valid(controller) then
            pcall(function() controller:SetControlRotation(initial) end)
            if manager_fov and unlock_fov then pcall(function() camera:UnlockFOV() end)
            elseif controller_fov and initial_fov then pcall(function() controller:FOV(initial_fov) end) end
        end
        self.changed=false
        self.applied_fov=nil
        self.locked_rotation=nil
    end
    function M:sample(real)
        -- Reassert the held controller orientation each engine frame, including
        -- frames without a new camera packet. Never extend its issued lease.
        if self.locked_rotation and self.changed and os.time()<=self.expiry then
            timed('camera_apply',function() controller:SetControlRotation(self.locked_rotation) end)
        end
        if real-self.last<.025 then return end;self.last=real
        local text;timed('camera_read',function() text=packets:read() end)
        if not text then if os.time()>self.expiry then self:stop() end;return end
        local values={};local valid=#text<4097
        for k,v in text:gmatch('([%w_]+)=([^\r\n]+)') do if values[k] then valid=false end;values[k]=v end
        local expiry=tonumber(values.expires_at) or 0;local seq=tonumber(values.sequence) or 0
        if not valid or values.Session~=session or expiry<os.time() or expiry>os.time()+2 then self:stop();return end
        self.expiry=expiry
        if values.enabled~='1' then self:stop();return end
        if seq<=self.sequence then return end
        assert(values.sequence==values.end_sequence,'Incomplete camera packet');self.sequence=seq
        local pitch=assert(tonumber(values.pitch));local yaw=assert(tonumber(values.yaw));local fov=tonumber(values.fov)
        assert(pitch==pitch and yaw==yaw and math.abs(pitch)<=90 and math.abs(yaw)<1e6,'Invalid host direction')
        local current=angles(api.call(controller,'GetControlRotation'));local actual=angles(api.call(camera,'GetCameraRotation'))
        local function correction(error)return math.max(-4,math.min(4,wrap(error)*.35)) end
        local target={Pitch=math.max(-80,math.min(80,wrap(current.Pitch)+correction(pitch-actual.Pitch))),Yaw=current.Yaw+correction(yaw-actual.Yaw),Roll=initial.Roll}
        if values.left_click_lock=='1' then
            if not self.locked_rotation then
                self.locked_rotation={Pitch=math.max(-80,math.min(80,wrap(current.Pitch)+wrap(pitch-actual.Pitch))),Yaw=current.Yaw+wrap(yaw-actual.Yaw),Roll=initial.Roll}
            end
            target=self.locked_rotation
        else self.locked_rotation=nil end
        timed('camera_apply',function() controller:SetControlRotation(target) end);self.changed=true;self.calls=self.calls+1
        if can_fov and fov and fov==fov and fov>=40 and fov<=130 and
            (not self.applied_fov or math.abs(fov-self.applied_fov)>.05) then
            if manager_fov and unlock_fov then camera:SetFOV(fov) else controller:FOV(fov) end
            self.applied_fov=fov
        end
        if self.status_time and real-self.status_time<.5 then return end;self.status_time=real
        timed('camera_status',function()
        local status=io.open(base..'guest-camera-follow-'..session..'.status','wb')
        if status then status:write('calls='..self.calls..'\nupdated_unix='..os.time()..'\nleft_click_lock='..(self.locked_rotation and 1 or 0)..'\npitch_error='..wrap(pitch-actual.Pitch)..'\nyaw_error='..wrap(yaw-actual.Yaw)..'\nfov_supported='..(can_fov and 1 or 0)..'\nfov_method='..(manager_fov and unlock_fov and 'camera_manager' or 'player_controller')..'\nactual_fov='..tostring(api.call(camera,'GetFOVAngle'))..'\nrequested_fov='..tostring(fov)..'\n');status:close() end
        end)
    end
    return M
end
