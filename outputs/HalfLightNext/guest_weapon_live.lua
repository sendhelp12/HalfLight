-- Bounded read-only source poses through the existing guarded match scheduler.
return function(api,pawn)
    local timed=api.timed or function(_,fn) fn() end
    local base=(HALFLIGHT_ROOT.."/work/lab/")
    local control=assert(io.open(base..'guest-live-control.ini','rb'))
    local text=control:read('*a');control:close()
    local session=text:match('Session=([a-f0-9]+)')
    local expiry=tonumber(text:match('ExpiresUnix=(%d+)')) or 0
    assert(session and #session==16 and expiry>os.time() and expiry<=os.time()+60,'Live source lease missing or invalid')
    local mode_file=io.open(base..'guest-session-mode-'..session..'.ini','rb')
    local mode=mode_file and mode_file:read('*a') or '';if mode_file then mode_file:close() end
    local continuous=text:match('Continuous=(%d+)')=='1' or (mode:match('Session=([a-f0-9]+)')==session and mode:match('Continuous=(%d+)')=='1')
    local follow_player=text:match('FollowPlayer=(%d+)')=='1'
    local source_pipe=text:match('SourcePipe=([^\r\n]+)')
    if source_pipe then assert(continuous and follow_player and source_pipe==[[\\.\pipe\HalfLightGuest-]]..session,'Unexpected source pipe') end
    local registry=assert(loadfile(HALFLIGHT_ROOT..'/outputs/HalfLightNext/guest_weapon_catalog.lua'))()(api)
    local first=assert(registry.profiles[1]);local profile_id,actor_class,component_name,weapon_index=first.id,first.class,first.component,0
    local source_scale={X=first.scale[1],Y=first.scale[2],Z=first.scale[3]};local expected_parts=first.parts
    local dual=true
    local function select_profile(weapon)
        if registry then
            local index,p=registry:match(weapon)
            if index then profile_id=p.id;actor_class=p.class;component_name=p.component;weapon_index=index;expected_parts=p.parts;source_scale={X=p.scale[1],Y=p.scale[2],Z=p.scale[3]} end
            return
        end
    end
    local function supported(name) return name:sub(1,#actor_class+1)==actor_class..' ' end
    local controller=api.call(pawn,'GetController')
    local camera=follow_player and api.read(controller,'PlayerCameraManager') or nil
    if follow_player then assert(api.valid(camera),'Guest camera unavailable') end
    local held_weapon=assert(loadfile((HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_held_weapon.lua")))()(api,pawn)
    local actor=held_weapon()
    select_profile(actor)
    local binding=base..'guest-live-weapon-'..session..'.txt'
    local root=api.valid(actor) and api.read(actor,'RootComponent') or nil
    local function pose_component(weapon)
        if not follow_player then return api.read(weapon,'RootComponent') end
        if registry then local index,_,component=registry:match(weapon);assert(index and api.valid(component),'Imported weapon components changed');return component end
    end
    local source_component
    local secondary_actor,secondary_component,secondary_index,secondary_scale,secondary_name
    if api.valid(actor) and supported(api.safe_text(actor)) then
        local matched,value=pcall(pose_component,actor)
        if matched then source_component=value end
    end
    if not source_component then actor=nil;root=nil end
    local component_note=assert(io.open(base..'guest-live-component-'..session..'.txt','wb'))
    component_note:write((api.safe_text(source_component)));component_note:close()
    local path=base..'guest-live-pose-'..session..'.csv'
    local sequence=0;local existing=continuous and io.open(path,'rb') or nil
    if existing then
        -- Reloads must not scan a growing session CSV on the game thread.
        -- Only the last complete row is needed to resume its sequence.
        local size=assert(existing:seek('end'));local offset=math.max(0,size-4096)
        assert(existing:seek('set',offset));if offset>0 then existing:read('*l') end
        local tail=existing:read(4096) or ''
        for line in tail:gmatch('([^\n]*)\n') do local previous=tonumber(line:match('^(%d+),'));if previous then sequence=previous end end
        existing:close()
    else
        local f=assert(io.open(path,'wb'))
        f:write('sequence,world_game_seconds,world_real_seconds,position_x_cm,position_y_cm,position_z_cm,quaternion_x,quaternion_y,quaternion_z,quaternion_w,scale_x,scale_y,scale_z'..(follow_player and ',camera_x_cm,camera_y_cm,camera_z_cm,camera_pitch,camera_yaw,camera_roll' or '')..'\n');f:close()
    end
    local saved=assert(io.open(binding,'wb'));saved:write((api.safe_text(actor)));saved:close()
    local M={path=path,sequence=sequence,last=-1,last_control=-1,last_wait=-1,waiting=false,stopped=false}
    local status=io.open(base..'guest-live-status-'..session..'.txt','wb')
    if status then
        status:write('reason='..(source_component and 'equipped' or 'waiting_equipped_weapon')..'\nprofile='..profile_id..'\npawn='..api.safe_text(pawn)..'\nsequence='..sequence..'\n');status:close()
    end
    local function connect_pipe()
        local output=io.open(source_pipe,'r+b');if not output then return end
        output:setvbuf('no')
        local previous=tonumber(output:read('*l'))
        if not previous or previous<0 or previous%1~=0 or previous>1e12 then output:close();error('Invalid source pipe handshake') end
        M.sequence=math.max(M.sequence,previous);M.output=output
    end
    if source_pipe then connect_pipe()
    else M.output=assert(io.open(path,'ab'));M.output:setvbuf('no') end
    function M:halt(reason)
        self.stopped=true
        self:flush()
        local status=io.open(base..'guest-live-status-'..session..'.txt','wb')
        if status then status:write('reason='..reason..'\nsequence='..self.sequence..'\n');status:close() end
    end
    function M:flush()
        if self.output then self.output:close();self.output=nil end
    end
    function M:sample(game,real)
        if self.stopped then return end
        if os.time()>=expiry then self:halt('lease_expired');return end
        if not self.output then
            if not self.pipe_attempt or real-self.pipe_attempt>=.1 then self.pipe_attempt=real;connect_pipe() end
            if not self.output then return end
        end
        -- Reflection and object-name lookup belong at the publication cadence,
        -- rather than on every engine frame between publications.
        if self.next_sample and real<self.next_sample then return end
        self.next_sample=(self.next_sample or real)+1/60
        if self.next_sample<real-1/60 then self.next_sample=real+1/60 end
        self.last=real
        -- Renew before waiting for an equipped item. A dropped or changed
        -- weapon must not permanently strand a continuous source.
        if real-self.last_control>=.25 then
            self.last_control=real
            local lease=io.open(base..'guest-live-control.ini','rb')
            if lease then
                local current=lease:read('*a');lease:close()
                local renewed=tonumber(current:match('ExpiresUnix=(%d+)')) or 0
                if current:match('Session=([a-f0-9]+)')~=session or renewed<=os.time() or renewed>os.time()+60 then self:halt('lease_revoked');return end
                expiry=renewed
            end
        end
        local held,held_name,hand
        timed('weapon_binding',function() held,hand=held_weapon();held_name=api.valid(held) and api.safe_text(held) or 'none' end)
        select_profile(held)
        -- A dropped axe is not a hand pose. Stop publishing until an actual
        -- equipped axe is available; expired transport releases forwarding.
        if not supported(held_name) then
            self.waiting=true
            if real-self.last_wait>=.25 then
                self.last_wait=real
                local note=io.open(base..'guest-live-status-'..session..'.txt','wb')
                if note then note:write('reason=waiting_equipped_weapon\nprofile='..profile_id..'\nheld='..held_name..'\npawn='..api.safe_text(pawn)..'\nsequence='..self.sequence..'\n');note:close() end
            end
            return
        end
        if self.waiting then
            self.waiting=false
            local note=io.open(base..'guest-live-status-'..session..'.txt','wb')
            if note then note:write('reason=equipped\nsequence='..self.sequence..'\n');note:close() end
        end
        if (continuous or not source_component) and held_name~=api.safe_text(actor) then
            local new_root=api.read(held,'RootComponent')
            if api.valid(new_root) then
                local matched,new_component=pcall(pose_component,held)
                if not matched then
                    self.waiting=true
                    if real-self.last_wait>=.25 then
                        self.last_wait=real
                        local note=io.open(base..'guest-live-status-'..session..'.txt','wb')
                        if note then note:write('reason=waiting_matching_weapon_parts\nprofile='..profile_id..'\nsequence='..self.sequence..'\n');note:close() end
                    end
                    return
                end
                actor=held;root=new_root;source_component=new_component
                local saved=assert(io.open(binding,'wb'));saved:write((api.safe_text(actor)));saved:close()
            end
        end
        if not api.valid(actor) then if continuous then return else self:halt('weapon_invalid');return end end
        if not continuous and held_name~=api.safe_text(actor) then self:halt('equipped_weapon_changed');return end
        local second=dual and held_weapon(hand=='R' and 'L' or 'R') or nil
        if api.safe_text(second)==held_name then second=nil end
        local second_name=api.safe_text(second)
        if second_name~=secondary_name then
            secondary_name=second_name
            secondary_actor=nil;secondary_component=nil;secondary_index=nil
            if api.valid(second) then
                select_profile(second)
                local matched,component=pcall(pose_component,second)
                if matched then secondary_actor=second;secondary_component=component;secondary_index=weapon_index;secondary_scale=source_scale end
                select_profile(held)
            end
        end
        if dual then
            local names=held_name..'\n'..api.safe_text(secondary_actor)
            if self.bound_names~=names then local saved=assert(io.open(binding,'wb'));saved:write(names);saved:close();self.bound_names=names end
        end
        if os.time()>=expiry then self:halt('lease_expired');return end
        local transform;timed('weapon_read',function() transform=assert(api.call(source_component,'K2_GetComponentToWorld'),'Weapon pose getter missing') end)
        local values={}
        for _,field in ipairs({'Translation','Rotation','Scale3D'}) do
            local v=api.read(transform,field)
            for _,axis in ipairs(field=='Rotation' and {'X','Y','Z','W'} or {'X','Y','Z'}) do
                local n=tonumber(api.read(v,axis));assert(n and n==n and math.abs(n)<1e6,'Invalid pose')
                if field=='Scale3D' then n=n/source_scale[axis] end
                values[#values+1]=n
            end
        end
        self.sequence=self.sequence+1;self.last=real
        local row={self.sequence,string.format('%.6f',game),string.format('%.6f',real)}
        for _,n in ipairs(values) do row[#row+1]=string.format('%.9g',n) end
        if follow_player then
            for _,getter in ipairs({'GetCameraLocation','GetCameraRotation'}) do
                local value=assert(api.call(camera,getter),'Guest camera getter unavailable')
                for _,axis in ipairs(getter=='GetCameraLocation' and {'X','Y','Z'} or {'Pitch','Yaw','Roll'}) do
                    local n=tonumber(api.read(value,axis));assert(n and n==n and math.abs(n)<1e6,'Invalid guest camera')
                    row[#row+1]=string.format('%.9g',n)
                end
            end
        end
        if dual then
            row[#row+1]=weapon_index;row[#row+1]=hand=='L' and 1 or 0;row[#row+1]=secondary_index or -1
            local other={0,0,0,0,0,0,1,1,1,1}
            if api.valid(secondary_component) then
                local transform;timed('weapon_read',function() transform=assert(api.call(secondary_component,'K2_GetComponentToWorld'),'Offhand pose getter missing') end)
                other={}
                for _,field in ipairs({'Translation','Rotation','Scale3D'}) do
                    local v=api.read(transform,field)
                    for _,axis in ipairs(field=='Rotation' and {'X','Y','Z','W'} or {'X','Y','Z'}) do
                        local n=tonumber(api.read(v,axis));assert(n and n==n and math.abs(n)<1e6,'Invalid offhand pose')
                        if field=='Scale3D' then n=n/secondary_scale[axis] end
                        other[#other+1]=n
                    end
                end
            end
            for _,n in ipairs(other) do row[#row+1]=string.format('%.9g',n) end
        end
        timed('weapon_write',function() assert(self.output:write(table.concat(row,',')..'\n')) end)
    end
    return M
end
