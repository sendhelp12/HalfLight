-- Guarded match scheduler for leased native bridge modules.
local create
create=function(api)
    -- A failed reflected getter returns one nil value, including in tonumber calls.
    if not api.halflight_single_results then
        for _,name in ipairs({'read','call'}) do local fn=api[name];api[name]=function(...) local value=fn(...);return value end end
        api.halflight_single_results=true
    end
    local M={stopped=false,started=false,sequence=0,error="none",rows={},last_flush=0,render_off=false,can_toggle_render=false}
    local out=(HALFLIGHT_ROOT.."/work/lab")
    local timings={}
    local function timed(name,fn)
        local before=os.clock();fn()
        local entry=timings[name] or {sum=0,count=0,max=0};timings[name]=entry
        local elapsed=(os.clock()-before)*1000
        entry.sum=entry.sum+elapsed;entry.count=entry.count+1;entry.max=math.max(entry.max,elapsed)
    end
    api.timed=timed
    local function numeric(value)
        local n=tonumber(value)
        if n and n==n and math.abs(n)<1e9 then return n end
        return nil
    end
    local function flush()
        if #M.rows==0 then return end
        local f=io.open(M.path,"ab")
        if not f then return end
        local ok=f:write(table.concat(M.rows,"\n") .. "\n");f:close();if ok then M.rows={} end
    end
    local function sample()
        if M.stopped then return true end
        if not api.valid(M.pawn) then
            M:stop();return true
        end
        local clocks_started=os.clock()
        local game=numeric(api.call(M.statics,"GetTimeSeconds",M.pawn))
        local real=numeric(api.call(M.statics,"GetRealTimeSeconds",M.pawn))
        local delta=numeric(api.call(M.statics,"GetWorldDeltaSeconds",M.pawn))
        if not game or not real or not delta then error("Reflected world-clock getters unavailable") end
        local clock_cost=(os.clock()-clocks_started)*1000
        local clocks=timings.clocks or {sum=0,count=0,max=0};timings.clocks=clocks
        clocks.sum=clocks.sum+clock_cost;clocks.count=clocks.count+1;clocks.max=math.max(clocks.max,clock_cost)
        M.frame_window=M.frame_window or real;M.frame_count=(M.frame_count or 0)+1
        M.delta_sum=(M.delta_sum or 0)+delta;M.delta_max=math.max(M.delta_max or 0,delta)
        if M.live_source and real-M.frame_window>=1 then
            local elapsed=real-M.frame_window
            local f=io.open(out..'\\guest-performance-'..M.live_session..'.txt','wb')
            if f then
                f:write('session='..M.live_session..'\nunix_seconds='..os.time()..'\nengine_frame_hz='..((M.frame_count-1)/elapsed)..
                    '\nmean_world_delta_ms='..(M.delta_sum/M.frame_count*1000)..'\nmax_world_delta_ms='..(M.delta_max*1000)..
                    '\nworld_rendering='..(M.render_off and 0 or 1)..'\nmetric=engine-frames;not-physics-substeps\n')
                for name,entry in pairs(timings) do
                    f:write(name..'_mean_clock_ms='..(entry.sum/entry.count)..'\n'..name..'_max_clock_ms='..entry.max..'\n')
                end
                f:close()
            end
            timings={}
            M.frame_window=real;M.frame_count=1;M.delta_sum=delta;M.delta_max=delta
        end
        if M.weapon_menu then timed('menu',function() M.weapon_menu:sample(real) end) end
        if M.catalog_capture then M.catalog_capture:sample(real,M.weapon_input and M.weapon_input.active) end
        if M.weapon_input then timed('input',function() M.weapon_input:sample(real) end) end
        -- A continuous session may start its floor publisher after the probe.
        -- Attach when the first valid packet arrives instead of missing it forever.
        if M.live_source and M.live_session and not M.world_collision and (not M.last_collision_check or real-M.last_collision_check>.25) then
            M.last_collision_check=real
            local control=io.open(out..'\\guest-floor-'..M.live_session..'.txt','rb')
            if control then
                local body=control:read(8193);control:close()
                if #body<=8192 and body:match('mode=rigid%-floor') and body:match('Session=([a-f0-9]+)')==M.live_session then
                    local path=(HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_rigid_floor.lua")
                    local ok,value=pcall(function() return assert(loadfile(path))()(api,M.pawn,M.live_session) end)
                    if ok then M.world_collision=value else M.error='Late floor bridge refused: '..tostring(value) end
                end
            end
        end
        if M.camera_follow then
            local ok,err=pcall(function() timed('camera',function() M.camera_follow:sample(real) end) end)
            if not ok then M.camera_follow.error=tostring(err);M.camera_follow:stop() end
        end
        local collision_active=not M.weapon_input or M.weapon_input.active
        if collision_active then
            if M.target_collision then M.target_collision:hold_stance() end
            if M.world_collision then timed('floor',function() M.world_collision:sample(real) end) end
            if M.target_collision and M.target_queries~=false then timed('targets',function() M.target_collision:sample(real) end) end
        elseif M.collision_active~=false then
            -- F8 off / expired input restores native weapon masks and disables
            -- guest proxies rather than continuing background physics writes.
            if M.world_collision then M.world_collision:stop() end
            if M.target_collision then M.target_collision:stop() end
        end
        M.collision_active=collision_active
        if M.camera_alignment then
            local ok,err=pcall(function() timed('alignment',function() M.camera_alignment:sample(real) end) end)
            if not ok then M.camera_alignment.error=tostring(err) end
        end
        if M.weapon_stream then
            local ok,err=pcall(function() timed('weapon',function() M.weapon_stream:sample(game,real) end) end)
            if not ok then
                print('[HalfLightNext] Weapon trace stopped: '..tostring(err)..'\n')
                pcall(function() M.weapon_stream:flush() end);M.weapon_stream=nil
            end
            if M.live_source and (not M.weapon_stream or M.weapon_stream.stopped) then M:stop();return true end
        end
        -- Live weapon sessions need only the weapon pose. Avoid the diagnostic
        -- bone getters and extra per-frame CSV while the user is playing.
        if M.live_source then M.sequence=M.sequence+1;return end
        local pose={}
        for _,bone in ipairs(M.bones) do
            local position=api.call(M.mesh,"GetSocketLocation",bone)
            for _,axis in ipairs({"X","Y","Z"}) do
                local value=numeric(position and api.read(position,axis))
                if not value then error("Invalid bone observation") end
                pose[#pose+1]=string.format("%.6f",value)
            end
        end
        M.sequence=M.sequence+1
        if #M.rows<240 then M.rows[#M.rows+1]=table.concat({M.sequence,os.time(),string.format("%.6f",game),
            string.format("%.6f",real),string.format("%.6f",delta),
            table.concat(pose,","),numeric(api.read(M.pawn,"Health")) or -1,M.render_off and 0 or 1},",") end
        if real-M.last_flush>=1 then flush();M.last_flush=real end
    end
    local function guarded_sample()
        local ok,err=pcall(sample)
        if not ok then
            M.error=tostring(err):gsub("[\r\n=]"," "):sub(1,220)
            print("[HalfLightNext] Tick probe stopped: " .. M.error .. "\n")
            M:stop()
        end
        return M.stopped
    end
    local function restore_render()
        if M.background_render then M.background_render:stop();M.render_off=M.background_render.off;return end
        if not M.render_off then return end
        local context=api.valid(M.pawn) and M.pawn or FindFirstOf("PlayerController")
        if not api.valid(context) then return end
        local ok=pcall(function() M.statics:SetEnableWorldRendering(context,true) end)
        if ok then M.render_off=false;print("[HalfLightNext] Guest world rendering restored.\n") end
    end
    local function render_policy()
        if M.background_render then
            -- Keep simulation-only rendering stable through F8-off menus and focus changes.
            M.background_render:sample(M.weapon_stream and not M.weapon_stream.stopped or false);M.render_off=M.background_render.off;return
        end
        local required=io.open(out.."\\guest-rendering-required.ini","rb")
        local policy=required and required:read("*a") or "";if required then required:close() end
        if policy:match("RequireRendering=(%d+)")=="1" then restore_render();return end
        local f=io.open(out .. "\\guest-probe-control.ini","rb")
        local text=f and f:read("*a") or "";if f then f:close() end
        local expiry=tonumber(text:match("ExpiresUnix=(%d+)")) or 0
        local now=os.time()
        local requested=text:match("WorldRendering=(%d+)")=="0" and expiry>now and expiry<=now+60
        if not requested or M.stopped then restore_render();return end
        if M.can_toggle_render and not M.render_off then
            local ok,err=pcall(function() M.statics:SetEnableWorldRendering(M.pawn,false) end)
            if ok then M.render_off=true;print("[HalfLightNext] Guest world rendering disabled by a bounded test lease.\n")
            else M.error=tostring(err):gsub("[\r\n=]"," "):sub(1,220) end
        end
    end
    function M:stop()
        if self.replacement then
            while self.replacement.replacement do self.replacement=self.replacement.replacement end
            self.replacement:stop();return
        end
        self.stopped=true
        restore_render()
        if self.handle and type(CancelDelayedAction)=="function" then pcall(CancelDelayedAction,self.handle) end
        pcall(flush)
        if self.weapon_stream then pcall(function() self.weapon_stream:flush() end) end
        if self.weapon_input then pcall(function() self.weapon_input:stop();self.weapon_input:close() end) end
        if self.catalog_capture then pcall(function() self.catalog_capture:stop() end) end
        if self.camera_follow then pcall(function() self.camera_follow:stop() end) end
        if self.world_collision then pcall(function() self.world_collision:stop() end) end
        if self.target_collision then pcall(function() self.target_collision:stop() end) end
        for _,module in pairs({self.camera_follow,self.world_collision,self.target_collision}) do
            if module.close then pcall(function() module:close() end) end
        end
    end
    function M:tick(pawn,seq,field)
        if self.replacement then
            while self.replacement.replacement do self.replacement=self.replacement.replacement end
            self.replacement:tick(pawn,seq,field);return
        end
        -- The persistent controller can possess a new match pawn while the old
        -- ragdoll is still valid. Release its modules and bind the actual pawn.
        if self.started and api.safe_text(pawn)~=self.pawn_identity then
            self:stop()
            self.replacement=create(api)
            self.replacement:tick(pawn,seq,field)
            return
        end
        if not self.started then
            self.started=true; self.pawn=pawn; self.pawn_identity=api.safe_text(pawn);self.mesh=api.read(pawn,"Mesh"); self.bones={}
            self.catalog_capture=assert(loadfile(HALFLIGHT_ROOT..'/outputs/HalfLightNext/guest_catalog_capture.lua'))()(api,pawn)
            local pose_module=(HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_weapon_pose.lua")
            local live_control=io.open(out.."\\guest-live-control.ini","rb")
            if live_control then
                local live_text=live_control:read("*a");live_control:close()
                local live_expiry=tonumber(live_text:match("ExpiresUnix=(%d+)")) or 0
                if live_expiry>os.time() and live_expiry<=os.time()+60 then
                    self.live_source=true
                    self.target_queries=live_text:match('GuestTargetQueries=(%d+)')~='0'
                    self.live_session=live_text:match('Session=([a-f0-9]+)')
                    local menu_file=io.open((HALFLIGHT_ROOT.."/.local/catalog.ini"),'rb')
                    if menu_file then
                        menu_file:close()
                        local menu_ok,menu=pcall(function() return assert(loadfile((HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_weapon_menu.lua")))()(api,pawn,self.live_session) end)
                        if menu_ok then self.weapon_menu=menu else self.error='Weapon menu refused: '..tostring(menu) end
                    end
                    pose_module=(HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_weapon_live.lua")
                    if live_text:match('Input=(%d+)')=='1' then
                        local session=live_text:match('Session=([a-f0-9]+)')
                        local input_module=(HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_weapon_input.lua")
                        local input_ok,input=pcall(function() return assert(loadfile(input_module))()(api,pawn,session) end)
                        if input_ok then self.weapon_input=input
                        else self.error='Host input refused: '..tostring(input) end
                        local collision_control=io.open(out..'\\guest-floor-'..session..'.txt','rb')
                        if collision_control then
                            local collision_text=collision_control:read(8193);collision_control:close()
                            local collision_module=(HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_world_collision.lua")
                            if collision_text:match('mode=rigid%-floor') then collision_module=(HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_rigid_floor.lua") end
                            local collision_ok,collision=pcall(function() return assert(loadfile(collision_module))()(api,pawn,session) end)
                            if collision_ok then self.world_collision=collision else self.error='Collision bridge refused: '..tostring(collision) end
                        end
                        local target_module=(HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_target_collision.lua")
                        local target_ok,target=pcall(function() return assert(loadfile(target_module))()(api,pawn,session) end)
                        if target_ok then self.target_collision=target else self.error='Target collision refused: '..tostring(target) end
                        local camera_module=(HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_camera_alignment.lua")
                        local camera_ok,diagnostics=pcall(function() return assert(loadfile(camera_module))()(api,pawn,self.mesh,session) end)
                        if camera_ok then self.camera_alignment=diagnostics else self.error='Camera diagnostics refused: '..tostring(diagnostics) end
                        local follow_module=(HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_camera_follow.lua")
                        local follow_ok,follow=pcall(function() return assert(loadfile(follow_module))()(api,pawn,session) end)
                        if follow_ok then self.camera_follow=follow else self.error='Camera follow refused: '..tostring(follow) end
                    end
                end
            end
            local stream_ok,stream=pcall(function() return assert(loadfile(pose_module))()(api,pawn) end)
            if stream_ok then self.weapon_stream=stream
            else print('[HalfLightNext] Weapon pose getter unavailable: '..tostring(stream)..'\n') end
            self.statics=StaticFindObject("/Script/Engine.Default__GameplayStatics")
            if not api.valid(self.statics) then self.error="GameplayStatics CDO unavailable";self.stopped=true end
            if not EngineTickAvailable or type(LoopInGameThreadAfterFrames)~="function" then
                self.error="Once-per-engine-frame scheduler unavailable";self.stopped=true
            end
            -- Pelvis and both hands are a small advancing-pose indicator, not a
            -- physics substep counter or a complete export of the skeleton.
            for i=0,math.min(tonumber(api.call(self.mesh,"GetNumBones")) or 0,256)-1 do
                local bone=api.call(self.mesh,"GetBoneName",i)
                local name=tostring(api.call(bone,"ToString") or ""):lower()
                if name=="pelvis" or name=="hand_l" or name=="hand_r" then self.bones[#self.bones+1]=bone end
            end
            if #self.bones~=3 then self.error="Expected pelvis and hand bones missing";self.stopped=true end
            local class=api.call(self.statics,"GetClass"); local descriptions={}
            if api.valid(class) then class:ForEachFunction(function(fn)
                local name=fn:GetFName():ToString()
                if name=="SetEnableWorldRendering" or name=="GetTimeSeconds" or name=="GetRealTimeSeconds" or name=="GetWorldDeltaSeconds" then
                    local params={}
                    fn:ForEachProperty(function(p) params[#params+1]=p:GetFullName() end)
                    descriptions[#descriptions+1]=api.safe_text(fn) .. "(" .. table.concat(params,",") .. ")"
                    if name=="SetEnableWorldRendering" and #params==2 and
                       params[1]:match("^ObjectProperty .+:WorldContextObject$") and
                       params[2]:match("^BoolProperty .+:bEnable$") then self.can_toggle_render=true end
                end
            end) end
            if self.live_source and self.weapon_input and self.can_toggle_render then
                local ok,module=pcall(function() return assert(loadfile((HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_background_rendering.lua")))()(api,pawn,self.statics,self.live_session) end)
                if ok then self.background_render=module else self.error='Background rendering refused: '..tostring(module) end
            end
            local f=io.open(out .. "\\guest-probe-reflection.txt","wb")
            if f then f:write(table.concat(descriptions,"\n"));f:close() end
            self.path=out .. "\\guest-engine-ticks-" .. os.time() .. ".csv"
            local file=assert(io.open(self.path,"wb"))
            file:write("sequence,unix_seconds,world_game_seconds,world_real_seconds,world_delta_seconds,bone0_x,bone0_y,bone0_z,bone1_x,bone1_y,bone1_z,bone2_x,bone2_y,bone2_z,health,world_rendering\n")
            file:close()
            if not self.stopped then self.handle=LoopInGameThreadAfterFrames(1,guarded_sample) end
            print("[HalfLightNext] Engine tick probe started; read-only, capture renderer disabled.\n")
        end
        render_policy()
        field("capture_state",self.stopped and "tick-probe-stopped" or "tick-probe-observing")
        field("capture_valid",0);field("next_probe_sequence",self.sequence);field("next_probe_error",self.error)
        field("next_probe_metric","engine-frame-and-three-bone-observation;not-physics-substeps")
        field("next_probe_world_rendering",self.render_off and 0 or 1)
        if self.weapon_input then
            field('native_source_damage_rate',tonumber(api.read(pawn,'Damage Rate (Additional)')) or -1)
            field('native_source_limb_damage_rate',tonumber(api.read(pawn,'Limb Damage Rate (Additional)')) or -1)
            field('native_source_self_trace_filters',self.weapon_input.self_trace_filters or 0)
            field('native_source_bleeding',tonumber(api.read(pawn,'Bleeding')) or -1)
            for _,part in ipairs({'Head','Head Health (Crush)','Neck','Back','Body Upper','Body Lower','Arm_R','Arm_L','Leg_R','Leg_L'}) do
                local name=part:find('Health',1,true) and part or part..' Health'
                field('native_source_'..name:gsub('[^%w]+','_'):lower(),tonumber(api.read(pawn,name)) or -1)
            end
            field('native_source_self_collision_guard',self.weapon_input.protected_mesh and 1 or 0)
            field('native_source_body_weapon_response',tonumber(api.call(self.mesh,'GetCollisionResponseToChannel',14)) or -1)
            field('native_input_session',self.weapon_input.session)
            field('native_input_active',self.weapon_input.active and 1 or 0)
            field('native_weapon_hand',self.weapon_input.hand or 'R')
            field('native_swap_active',self.weapon_input.swap_down and 1 or 0)
            field('native_swapping',api.read(pawn,'Swapping weapons')==true and 1 or 0)
            field('native_alt_active',self.weapon_input.alt_down and 1 or 0)
            field('native_alt_key_down',api.read(pawn,'Alt Key Down (cont)')==true and 1 or 0)
            field('native_alt_thrusting',api.read(pawn,'Alt Thrusting')==true and 1 or 0)
            field('native_alt_temp',api.read(pawn,'Alt Thrust Key Down (temp)')==true and 1 or 0)
            field('native_right_thrusting',api.read(pawn,'R_Thrusting')==true and 1 or 0)
            field('native_alt_classic_toggle',api.read(api.read(pawn,'GI Settings'),'Classic Alt Thrust Toggle')==true and 1 or 0)
            field('native_alt_presses',self.weapon_input.alt_presses or 0)
            field('native_alt_press_key_down',self.weapon_input.alt_press_native and 1 or 0)
            field('native_alt_press_thrusting',self.weapon_input.alt_press_thrusting and 1 or 0)
            field('native_alt_release_key_down',self.weapon_input.alt_release_native and 1 or 0)
            field('native_alt_guard_after',self.weapon_input.alt_guard_after and 1 or 0)
            field('native_alt_thrust_after',self.weapon_input.alt_thrust_after and 1 or 0)
            field('native_right_guarding',api.read(pawn,'R_Guarding')==true and 1 or 0)
            field('native_left_guarding',api.read(pawn,'L_Guarding')==true and 1 or 0)
            field('native_left_guard_requested',self.weapon_input.left or 0)
            field('native_two_hand_selected',api.read(pawn,'R Two Handed Grip')==true and 1 or 0)
            field('native_any_guarding',api.read(pawn,'Any_Guarding')==true and 1 or 0)
            field('native_right_thrust_alpha',api.read(pawn,'R Thrust Alpha') or 0)
            field('native_left_thrust_alpha',api.read(pawn,'L Thrust Alpha') or 0)
            field('native_right_thrust_position',api.read(pawn,'R Thrust Position Alpha') or 0)
            field('native_left_thrust_position',api.read(pawn,'L Thrust Position Alpha') or 0)
            field('native_right_thrust_target',api.read(pawn,'Alt Thrust R') or 0)
            field('native_left_thrust_target',api.read(pawn,'Alt Thrust L') or 0)
            field('native_thrust_repairs',self.weapon_input.thrust_repairs or 0)
            field('native_alt_guard_repairs',self.weapon_input.guard_repairs or 0)
            field('native_input_calls',self.weapon_input.calls)
            field('native_input_mouse_calls',self.weapon_input.mouse_calls)
            field('native_swing_axis_repairs',self.weapon_input.swing_repairs or 0)
            field('native_swing_axis_x',api.read(pawn,'Axis Value X') or 0)
            field('native_swing_axis_y',api.read(pawn,'Axis Value Y') or 0)
            field('native_swing_axis_x_interp',api.read(pawn,'Axis Value X Interp') or 0)
            field('native_input_error',self.weapon_input.error)
            field('native_grip_attached',api.read(pawn,'L Hand In Offhand Attached')==true and 1 or 0)
        end
    end
    return M
end
return create
