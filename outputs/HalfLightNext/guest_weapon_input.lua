-- Game-specific reflected input, not Windows input injection.
return function(api,pawn,session)
    local palm_frame=assert(loadfile(HALFLIGHT_ROOT..'/outputs/HalfLightNext/guest_palm_frame.lua'))()
    local registry;local catalog_file=io.open((HALFLIGHT_ROOT.."/.local/catalog.ini"),'rb')
    if catalog_file then catalog_file:close();registry=assert(loadfile((HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_weapon_catalog.lua")))()(api) end
    local weapon_count=registry and registry.count or 2
    local function index_of(weapon)
        if registry then return registry:match(weapon) end
        return api.safe_text(weapon):match('^ModularWeaponBP_C ') and 1 or 0
    end
    local names={right='InpAxisEvt_Right Guard Axis_K2Node_InputAxisEvent_6',
        left='InpAxisEvt_Left Guard Axis_K2Node_InputAxisEvent_7',
        x='InpAxisEvt_Turn Right / Left Mouse_K2Node_InputAxisEvent_16',
        y='InpAxisEvt_Look Up / Down Mouse_K2Node_InputAxisEvent_17',
        grip_press='InpActEvt_RightMouseButton_K2Node_InputKeyEvent_1',
        grip_release='InpActEvt_RightMouseButton_K2Node_InputKeyEvent_0',
        alt_press='InpActEvt_Thrust_K2Node_InputActionEvent_0',
        alt_release='InpActEvt_Thrust_K2Node_InputActionEvent_1',
        swap_press='InpActEvt_Swap Hands_K2Node_InputActionEvent_16',
        swap_release='InpActEvt_Swap Hands_K2Node_InputActionEvent_17'}
    local class=api.call(pawn,'GetClass');local found={};local hook_paths={}
    assert(api.valid(class),'Character class unavailable')
    class:ForEachFunction(function(fn)
        local name=fn:GetFName():ToString()
        for key,expected in pairs(names) do if name==expected then
            local params={};fn:ForEachProperty(function(p) params[#params+1]=p:GetFullName() end)
            local grip=key:match('^grip_') or key:match('^alt_') or key:match('^swap_')
            assert(#params==1 and params[1]:match(grip and '^StructProperty ' or '^FloatProperty ') and params[1]:match(grip and ':Key$' or ':AxisValue$'),'Unexpected input signature: '..name..'|'..table.concat(params,'|'))
            found[key]=true
            if key=='right' or key=='left' or key=='x' or key=='y' then hook_paths[key]=fn:GetFullName():gsub('^Function ','') end
        end end
    end)
    for key in pairs(names) do assert(found[key],'Input function missing: '..key) end
    local attachment_property,two_hand_property
    if class.ForEachProperty then class:ForEachProperty(function(p)
        local full=p:GetFullName();local name=full:match(':([^:]+)$')
        if full:match('^BoolProperty ') and name and name:gsub('[%s_]',''):lower()=='lhandinoffhandattached' then attachment_property=name end
        if full:match('^BoolProperty ') and name and name:gsub('[%s_]',''):lower()=='rtwohandedgrip' then two_hand_property=name end
    end) end
    local M={two_hand_property=two_hand_property,session=session,active=false,calls=0,mouse_calls=0,last_seq=0,last_real=0,last_x=0,last_y=0,baseline=false,error='none'}
    local held_weapon=assert(loadfile((HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_held_weapon.lua")))()(api,pawn)
    local hooks={}
    local pawn_address=api.call(pawn,'GetAddress')
    local pawn_name=api.safe_text(pawn)
    local function owns(owner)
        if not api.valid(pawn) or not api.valid(owner) then return false end
        if type(pawn_address)=='number' and pawn_address>0 then return api.call(owner,'GetAddress')==pawn_address end
        return api.safe_text(owner)==pawn_name
    end
    local path=(HALFLIGHT_ROOT.."/work/lab/guest-input-")..session..'.txt'
    local packets=assert(loadfile((HALFLIGHT_ROOT.."/outputs/HalfLightNext/guest_packet_reader.lua")))()(path,4096)
    local grip_path=(HALFLIGHT_ROOT.."/work/lab/guest-grip-")..session..'.txt'
    local diagnostic_path=grip_path:gsub('%.txt$','.status')
    -- Native key events accompany the physical guard edges below.
    local key={KeyName=FName('RightMouseButton')}
    local alt_key={KeyName=FName('LeftAlt')}
    local swap_key={KeyName=FName('X')}
    local function axis(name,value) pawn[names[name]](pawn,value);M.calls=M.calls+1 end
    local function restore_body()
        if M.damage_rates and api.valid(pawn) then
            for name,value in pairs(M.damage_rates) do
                pawn[name]=value;assert(api.read(pawn,name)==value,'Source damage rate restoration failed: '..name)
            end
        end
        M.damage_rates=nil
        if M.protected_mesh and api.valid(M.protected_mesh) then
            M.protected_mesh:SetCollisionResponseToChannel(14,M.body_weapon_response)
            assert(M.protected_mesh:GetCollisionResponseToChannel(14)==M.body_weapon_response,'Source body mask restoration failed')
        end
        M.protected_mesh=nil;M.body_weapon_response=nil
    end
    local function protect_body()
        if not M.damage_rates then
            local saved={}
            for _,name in ipairs({'Damage Rate (Additional)','Limb Damage Rate (Additional)'}) do
                local value=tonumber(api.read(pawn,name))
                assert(value and value==value and math.abs(value)<1e6,'Source damage rate unavailable: '..name)
                saved[name]=value
            end
            M.damage_rates=saved
        end
        for name in pairs(M.damage_rates) do
            if api.read(pawn,name)~=0 then
                pawn[name]=0;assert(api.read(pawn,name)==0,'Source damage rate still active: '..name)
            end
        end
        local mesh=api.read(pawn,'Mesh')
        if M.protected_mesh==mesh then return end
        -- Changing a mesh must not restore the already-active damage guard.
        if M.protected_mesh and api.valid(M.protected_mesh) then M.protected_mesh:SetCollisionResponseToChannel(14,M.body_weapon_response) end
        assert(api.valid(mesh) and mesh:GetCollisionObjectType()==16,'Verified source body mesh required')
        local response=mesh:GetCollisionResponseToChannel(14)
        assert(response>=0 and response<=2,'Invalid source body weapon response')
        M.protected_mesh=mesh;M.body_weapon_response=response
        -- Half Sword is the physics controller during forwarding: its weapons
        -- must not injure its own anchored body. Host damage and proxy masks are separate.
        mesh:SetCollisionResponseToChannel(14,0)
        assert(mesh:GetCollisionResponseToChannel(14)==0,'Source body still blocks weapons')
    end
    local function guard(name,value)
        local side=name=='left' and 'L' or 'R'
        -- Button-down also selects native grips; thrust only changes guarding.
        local down=M['physical_'..name]==1
        if api.read(pawn,side..' Down')~=down then pawn[side..' Down']=down end
        if api.read(pawn,side..'_Guarding')~=(value==1) then pawn[side..'_Guarding']=value==1 end
        if value==1 and M.alt_down and api.read(pawn,'Alt Thrusting')~=true then pawn['Alt Thrusting']=true end
    end
    local function set_swap(down)
        if down~=(M.swap_down or false) and api.valid(pawn) then
            pawn[down and names.swap_press or names.swap_release](pawn,swap_key)
            M.swap_down=down
        end
    end
    local function set_alt(down)
        if down~=(M.alt_down or false) and api.valid(pawn) then
            pawn[down and names.alt_press or names.alt_release](pawn,alt_key)
            M.alt_down=down
            if down then
                M.alt_presses=(M.alt_presses or 0)+1
                M.alt_press_native=api.read(pawn,'Alt Key Down (cont)')==true
                M.alt_press_thrusting=api.read(pawn,'Alt Thrusting')==true
            else
                M.alt_release_native=api.read(pawn,'Alt Key Down (cont)')==true
            end
        end
    end
    -- Clear a held native modifier, including one left by the old reversed mapping.
    M.alt_down=api.read(pawn,'Alt Key Down (cont)')==true
    set_alt(false)
    local function release_grip()
        if M.rmb_down and api.valid(pawn) then pawn[names.grip_release](pawn,key) end
        M.rmb_down=false;M.owns_grip=false
    end
    function M:stop()
        self.active=false;self.control_deadline=0
        self.forwarding_x=false;self.forwarding_y=false;self.swing_axes=nil;self.thrust_r=nil;self.thrust_l=nil
        pcall(set_alt,false)
        pcall(set_swap,false)
        if self.baseline and api.valid(pawn) then pcall(axis,'right',0);pcall(axis,'left',0) end
        release_grip()
        restore_body()
        self.active=false;self.baseline=false;self.axis_right=nil;self.axis_left=nil
    end
    function M:close()
        self:stop()
        for _,hook in ipairs(hooks) do UnregisterHook(table.unpack(hook)) end
        hooks={};packets:close()
    end
    function M:sample(real)
        local ok,err=pcall(function()
            local text=packets:read() or ''
            local values={};local valid=#text<4097
            for key,value in text:gmatch('([%w_]+)=([^\r\n]+)') do if values[key] then valid=false end;values[key]=value end
            local seq=tonumber(values.seq) or 0;local expiry=tonumber(values.expires_at) or 0
            if not api.valid(pawn) then self:stop();return end
            if not valid or values.Session~=session or seq<=0 or values.seq~=values.end_seq or
                expiry<os.time() or expiry>os.time()+1 or (values.enabled~='1' and values.enabled~='0') then
                if self.active and (real-self.last_real>.25 or os.time()>self.expiry) then self:stop() end
                return
            end
            if values.enabled=='0' then self:stop();return end
            if seq==self.last_seq then if real-self.last_real>.25 then self:stop() end;return end
            assert(seq>self.last_seq,'Input sequence went backward')
            local x=assert(tonumber(values.mouse_x));local y=assert(tonumber(values.mouse_y))
            assert(x==x and y==y and math.abs(x)<1e12 and math.abs(y)<1e12,'Invalid mouse counters')
            local right=tonumber(values.right_guard);local left=tonumber(values.left_guard)
            assert((right==0 or right==1) and (left==0 or left==1),'Invalid guard values')
            local alt=values.alt==nil and 0 or tonumber(values.alt)
            assert(alt==0 or alt==1,'Invalid Alt value')
            local swap=values.swap==nil and 0 or tonumber(values.swap)
            assert(swap==0 or swap==1,'Invalid swap value')
            self.control_deadline=os.clock()+.25;self.expiry=expiry
            protect_body()
            set_alt(alt==1)
            set_swap(swap==1)
            local weapon,hand=held_weapon();hand=hand or self.hand or 'R';self.hand=hand
            local weapon_index=index_of(weapon) or 0
            local other,other_hand=held_weapon(hand=='R' and 'L' or 'R')
            local other_index=index_of(other)
            if not api.valid(other) or api.safe_text(other)==api.safe_text(weapon) or other_index==nil then other=nil;other_hand=nil;other_index=0 end
            other_index=other_index+weapon_count
            local nr=right;local nl=left
            self.right=nr;self.left=nl;self.physical_right=nr;self.physical_left=nl
            local offhand=api.read(pawn,hand=='R' and 'Weapon L' or 'Weapon R')
            local free=not api.valid(offhand) or api.safe_text(offhand):match('^Weapon_Fists_C ')~=nil or (api.valid(weapon) and api.safe_text(offhand)==api.safe_text(weapon))
            if hand=='R' and left==1 and not self.rmb_down and free and api.valid(weapon) and attachment_property and two_hand_property then
                pawn[names.grip_press](pawn,key);self.owns_grip=true;self.rmb_down=true
            elseif hand~='R' or left==0 or not free or not api.valid(weapon) then
                release_grip()
            end
            -- Native guard events have click gates. Renew held flags without replaying presses.
            if self.axis_right~=nr then axis('right',nr);self.axis_right=nr end
            if self.axis_left~=nl then axis('left',nl);self.axis_left=nl end
            local desired=two_hand_property and api.read(pawn,two_hand_property)==true
            local attached=attachment_property and api.read(pawn,attachment_property)==true
            -- RMB edges select the grip; LMB drives both attached hands afterward.
            if hand=='R' and alt==1 and right==1 and desired and attached and free and api.valid(weapon) then self.right=1;self.left=1 end
            guard('right',self.right);guard('left',self.left)
            if alt==1 and right==1 then
                self.alt_guard_after=api.read(pawn,'R_Guarding')==true
                self.alt_thrust_after=api.read(pawn,'Alt Thrusting')==true
            end
            local grip_signature=api.safe_text(weapon)..'|'..hand..'|'..api.safe_text(other)..'|'..tostring(other_hand)
            if not self.grip_time or real-self.grip_time>=.05 or self.grip_signature~=grip_signature then
                self.grip_signature=grip_signature
                self.grip_time=real
                local function publish_grip(current,current_hand,index,primary)
                local root=api.valid(current) and api.read(current,'RootComponent') or nil;local offset=0
                if registry then local _,profile,component=registry:match(current);if profile then root=component;offset=profile.offset or 0 end end
                local mesh=api.read(pawn,'Mesh')
                local valid_scene=api.valid(root) and api.valid(mesh)
                local socket={1,0,0,0,0,1,0,0,0,0,1,0};local right_socket=socket
                if valid_scene then
                    if current_hand=='R' then
                        local value=palm_frame(api,pawn,root,'r',offset)
                        valid_scene=value~=nil;right_socket=value or right_socket
                    end
                    if current_hand=='L' or (current_hand=='R' and desired and free and attached) then
                        local value=palm_frame(api,pawn,root,'l',offset)
                        valid_scene=valid_scene and value~=nil;socket=value or socket
                    end
                end
                local body='Session='..session..'\nseq='..seq..'\nend_seq='..seq..'\nexpires_at='..(os.time()+1)..
                    '\nenabled='..(valid_scene and '1' or '0')..'\nleft_enabled='..((current_hand=='L' or (current_hand=='R' and desired and free and attached)) and valid_scene and '1' or '0')..
                    '\nsocket='..table.concat(socket,',')..'\nright_socket='..table.concat(right_socket,',')..
                    '\nright_enabled='..(current_hand=='R' and valid_scene and '1' or '0')..'\nweapon_index='..index..'\n'
                local paths={grip_path:gsub('%.txt$','-'..index..'.txt')};if primary then paths[#paths+1]=grip_path end
                for _,path in ipairs(paths) do local f=io.open(path,'wb');if f then f:write(body);f:close() end end
                if primary then
                local diagnostic_text='requested='..tostring(desired)..'\nfree='..tostring(free)..'\nowned='..tostring(self.owns_grip)..'\nattached='..tostring(attached)..'\nproperty='..tostring(attachment_property)..'\nroot='..api.safe_text(root)..'\npress_function='..names.grip_press..'\nsocket_valid='..tostring(valid_scene)..'\n'
                if diagnostic_text~=self.last_diagnostic then
                    local diagnostic=io.open(diagnostic_path,'wb')
                    if diagnostic then diagnostic:write(diagnostic_text);diagnostic:close();self.last_diagnostic=diagnostic_text end
                end
                end
                end
                publish_grip(weapon,hand,weapon_index,true)
                publish_grip(other,other_hand,other_index,false)
                if self.other_grip_index and self.other_grip_index~=other_index then publish_grip(nil,nil,self.other_grip_index,false) end
                self.other_grip_index=other_index
            end
            if self.baseline and (right==1 or left==1) then
                -- Cumulative raw counts cover every skipped input packet. A
                -- 64-count cap discarded ordinary broad/high-DPI swings.
                local dx=math.max(-4096,math.min(4096,x-self.last_x))*.2
                local dy=math.max(-4096,math.min(4096,y-self.last_y))*.2
                self.forwarding_x=true;axis('x',dx);self.forwarding_x=false
                self.forwarding_y=true;axis('y',dy);self.forwarding_y=false
                self.swing_axes={}
                for _,name in ipairs({'Axis Value X','Axis Value X Interp','Axis Value Y','Axis Value Y Interp'}) do
                    local value=tonumber(api.read(pawn,name));if value and value==value and math.abs(value)<1e6 then self.swing_axes[name]=value end
                end
                if self.alt_down then
                    self.thrust_r=tonumber(api.read(pawn,'Alt Thrust R'));self.thrust_l=tonumber(api.read(pawn,'Alt Thrust L'))
                    assert(self.thrust_r and self.thrust_r>=0 and self.thrust_r<=1 and self.thrust_l and self.thrust_l>=0 and self.thrust_l<=1,'Invalid native thrust targets')
                else self.thrust_r=nil;self.thrust_l=nil end
                if dx~=0 or dy~=0 then self.mouse_calls=self.mouse_calls+1 end
            else self.swing_axes=nil end
            self.active=true;self.baseline=true;self.last_seq=seq;self.last_real=real;self.last_x=x;self.last_y=y
            self.expiry=expiry
        end)
        if not ok then self.error=tostring(err);self:stop() end
    end
    -- Background physical axes report zero. Restore this pawn's fresh guard
    -- flags without replaying click events, before native swing/physics runs.
    assert(type(RegisterHook)=='function' and type(UnregisterHook)=='function','Guard input hooks unavailable')
    for _,name in ipairs({'right','left','x','y'}) do
        local path=hook_paths[name]
        local ok,pre,post=pcall(RegisterHook,path,function(context,value)
            if not M.active or os.clock()>M.control_deadline or os.time()>M.expiry then return end
            local owner=context:get()
            if not owns(owner) then return end
            if name=='x' or name=='y' then
                if M['forwarding_'..name] or value:get()~=0 then return end
                if M.swing_axes then
                    local axis=name:upper();local repaired=false
                    for _,field in ipairs({'Axis Value '..axis,'Axis Value '..axis..' Interp'}) do
                        local desired=M.swing_axes[field]
                        if desired~=nil and api.read(pawn,field)~=desired then pawn[field]=desired;repaired=true end
                    end
                    if repaired then M.swing_repairs=(M.swing_repairs or 0)+1 end
                end
                if name=='x' then return end
                -- Native background mouse-zero replaces thrust targets before physics.
                -- Keep the native targets from forwarded movement; do not replay pitch input.
                if not M.alt_down or M.forwarding_y or value:get()~=0 or M.thrust_r==nil then return end
                if api.read(pawn,'Alt Thrust R')==M.thrust_r and api.read(pawn,'Alt Thrust L')==M.thrust_l then return end
                local repaired,err=pcall(function() pawn['Alt Thrust R']=M.thrust_r;pawn['Alt Thrust L']=M.thrust_l end)
                if not repaired then M.error=tostring(err);M:stop();return end
                M.thrust_repairs=(M.thrust_repairs or 0)+1
                return
            end
            local desired=M[name]
            if value:get()==desired then return end
            local repaired,err=pcall(guard,name,desired)
            if not repaired then M.error=tostring(err);M:stop();return end
            M.guard_repairs=(M.guard_repairs or 0)+1
        end)
        if not ok then M:close();error(pre) end
        hooks[#hooks+1]={path,pre,post}
    end
    -- Native flesh sweeps use object queries with IgnoreSelf=false. Collision
    -- responses alone cannot exclude the querying character from that route.
    local trace_path='/Script/Engine.KismetSystemLibrary:SphereTraceMultiForObjects'
    local ok,pre,post=pcall(RegisterHook,trace_path,function(_,world,_,_,_,_,_,_,_,_,ignore_self)
        if not M.active or os.clock()>M.control_deadline or os.time()>M.expiry then return end
        local owner=world:get()
        if not owns(owner) then return end
        ignore_self:set(true);M.self_trace_filters=(M.self_trace_filters or 0)+1
    end)
    if not ok then M:close();error(pre) end
    hooks[#hooks+1]={trace_path,pre,post}
    return M
end
