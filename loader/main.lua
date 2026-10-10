-- HalfLightBridge 0.1: native Half Sword player telemetry; no gameplay changes.
local filename=debug.getinfo(1,'S').source:gsub('^@','')
local directory=assert(filename:match('^(.*[/\\])'),'HalfLight loader location unavailable')
local file=assert(io.open(directory..'halflight-root.txt','rb'),'Run HalfLight Setup first')
local root=file:read(4097);file:close()
assert(root and #root<=4096,'Invalid HalfLight setup path')
HALFLIGHT_ROOT=root:gsub('[\r\n]+$',''):gsub('\\','/')
assert(HALFLIGHT_ROOT:match('^[A-Za-z]:/') or HALFLIGHT_ROOT:match('^//'),'HalfLight setup path must be absolute')
local runtime=HALFLIGHT_ROOT..'/outputs/HalfLightNext/runtime'
local run_id = os.getenv("HLB_RUN_ID")
-- Steam can retain environment variables from an earlier launch. The session
-- file is authoritative whenever it is available.
do
    local session=io.open(runtime .. "\\session.ini", "rb")
    if session then
        local text=session:read("*a"); session:close()
        run_id=text:match("RunId=([%w%-]+)") or run_id
    end
end
if not runtime or not run_id then
    print("[HalfLightBridge] Launch with Launch Bridge.cmd to start telemetry.\n")
    return
end
local seq, last_error, peer_announced = 0, nil, false
local cached_controller, cached_pawn
local function valid(obj)
    if obj == nil then return false end
    local ok, result = pcall(function() return obj:IsValid() end)
    return ok and result
end
local function read(obj, property)
    local ok, value = pcall(function() return obj[property] end)
    if ok then return value end
end
local function call(obj, method, ...)
    local args = {...}
    local ok, value = pcall(function() return obj[method](obj, table.unpack(args)) end)
    if ok then return value end
end
local function safe_text(obj)
    if not valid(obj) then return "none" end
    local name = call(obj, "GetFullName") or "unknown"
    return tostring(name):gsub("[\r\n=]", " ")
end
local function find_player()
    if not valid(cached_controller) then
        cached_controller = FindFirstOf("PlayerController")
    end
    if not valid(cached_controller) then return nil end
    -- Resolve from the controller so enemy instances of the same class are not selected.
    cached_pawn = read(cached_controller, "Pawn")
    if not valid(cached_pawn) then cached_pawn = call(cached_controller, "K2_GetPawn") end
    return valid(cached_pawn) and cached_pawn or nil
end
local function peer_sequence()
    local f = io.open(runtime .. "\\to-half-sword.txt", "rb")
    if not f then return 0 end
    local content = f:read("*a"); f:close()
    if #content > 4096 then return 0 end
    if not content:find("run_id=" .. run_id .. "\n", 1, true) or
       not content:find("source=dying-light\n", 1, true) then return 0 end
    local expiry=tonumber(content:match("\nexpires_at=(%d+)\n"))
    if not expiry or expiry<os.time() then return 0 end
    return tonumber(content:match("\nseq=(%d+)\n")) or 0
end
local function finite(value)
    local n = tonumber(value)
    return n and n == n and math.abs(n) < 1e9 and n or 0
end
local capture,capture_epoch,bone_cache
local function capture_tick(pawn,field)
    -- Splash/menu maps possess BP_FreeCamera, not a physical character.
    -- Never build pose/equipment/input callbacks against that temporary pawn.
    -- The hub also has a Character-derived preview pawn. Only the physical
    -- match pawn has the mesh and reflected weapon events verified here.
    if not valid(pawn) or not safe_text(pawn):match("^Willie_BP_C ") or
       call(pawn,"IsA","/Script/Engine.Character")~=true then
        if capture then capture:stop();capture=nil end
        field("capture_state","waiting-for-character");field("capture_valid",0);return
    end
    local config=io.open(runtime .. "\\actor-capture.ini","rb")
    local settings=config and config:read("*a") or "";if config then config:close() end
    local enabled=settings:match("Enabled=(%d+)")=="1"
    local epoch=settings:match("Epoch=(%d+)") or "0"
    if not enabled then
        if capture then capture:stop();capture=nil end
        field("capture_state","disabled");field("capture_valid",0);return
    end
    if not capture or capture_epoch~=epoch then
        if capture then capture:stop() end
        local chunk,err=loadfile(runtime .. "\\actor_capture.lua")
        if not chunk then field("capture_state",tostring(err):gsub("[\r\n=]"," "));return end
        capture=chunk()({valid=valid,read=read,call=call,safe_text=safe_text,finite=finite,runtime=runtime,
            pelvis_location=function(mesh)
                for _,bone in ipairs(bone_cache.selected) do
                    if bone.text:lower()=="pelvis" then return call(mesh,"GetSocketLocation",bone.name) end
                end
            end})
        capture_epoch=epoch
    end
    capture:tick(pawn,seq,field)
end
bone_cache = {mesh="none", scanned=0, total=0, selected={}, parents={}, indices={}}
local function fname_text(name)
    if name == nil then return nil end
    local text=type(name)=="string" and name or call(name,"ToString")
    if not text or text=="None" or text=="" then return nil end
    return tostring(text):gsub("[\r\n=]", " ")
end
local function skeleton(mesh, field)
    local identity=safe_text(mesh)
    if identity~=bone_cache.mesh then
        bone_cache={mesh=identity, scanned=0, total=0, selected={}, parents={}, indices={}}
        bone_cache.total=math.min(math.max(tonumber((call(mesh,"GetNumBones"))) or 0,0),256)
    end
    -- Discover in small batches so a new pawn never causes a long game-thread scan.
    for index=bone_cache.scanned,math.min(bone_cache.total-1,bone_cache.scanned+31) do
        local name=call(mesh,"GetBoneName",index)
        local text=fname_text(name)
        if text then
            bone_cache.parents[text]=fname_text(call(mesh,"GetParentBone",name))
            local lower=text:lower()
            local important=index==0
            for _,part in ipairs({"pelvis","hip","spine","chest","neck","head","clavicle","arm","hand","thigh","calf","leg","foot"}) do
                if lower:find(part,1,true) then important=true end
            end
            for _,part in ipairs({"finger","thumb","index","middle","ring","pinky","twist","ik_","hair","face","eye","jaw","tongue","end"}) do
                if lower:find(part,1,true) then important=false end
            end
            if important and #bone_cache.selected<32 then
                bone_cache.indices[text]=#bone_cache.selected
                bone_cache.selected[#bone_cache.selected+1]={name=name,text=text}
            end
        end
        bone_cache.scanned=index+1
    end
    field("skeleton_total_bones",bone_cache.total)
    field("bone_count",#bone_cache.selected)
    for index,bone in ipairs(bone_cache.selected) do
        local prefix="bone_" .. (index-1) .. "_"
        local parent=bone_cache.parents[bone.text]
        for _=1,32 do
            if not parent or bone_cache.indices[parent]~=nil then break end
            parent=bone_cache.parents[parent]
        end
        local position=call(mesh,"GetSocketLocation",bone.name)
        field(prefix .. "name",bone.text)
        field(prefix .. "parent",parent and bone_cache.indices[parent] or -1)
        local xyz={}
        for _,axis in ipairs({"X","Y","Z"}) do xyz[#xyz+1]=tonumber(position and read(position,axis)) end
        local good=#xyz==3
        for _,value in ipairs(xyz) do if value~=value or math.abs(value)>=1e9 then good=false end end
        field(prefix .. "valid",good and 1 or 0)
        for i,axis in ipairs({"x","y","z"}) do field(prefix .. axis,good and xyz[i] or 0) end
    end
end
local function tick()
    seq = seq + 1
    local pawn = find_player()
    local location = pawn and call(pawn, "K2_GetActorLocation")
    local rotation = pawn and call(pawn, "K2_GetActorRotation")
    local velocity = pawn and call(pawn, "GetVelocity")
    local camera = read(cached_controller, "PlayerCameraManager")
    local camera_location = valid(camera) and call(camera, "GetCameraLocation")
    local camera_rotation = valid(camera) and call(camera, "GetCameraRotation")
    local peer = peer_sequence()
    if peer > 0 and not peer_announced then
        print("[HalfLightBridge] Received Dying Light heartbeat through relay.\n")
        peer_announced = true
    end
    local lines = {
        "protocol=1", "run_id=" .. run_id, "source=half-sword", "seq=" .. seq,
        "peer_ack=" .. peer, "player_valid=" .. (pawn and "1" or "0"),
        "pawn=" .. safe_text(pawn), "controller=" .. safe_text(cached_controller),
        "mesh=" .. safe_text(pawn and read(pawn, "Mesh")),
    }
    local function field(key, value) lines[#lines+1] = key .. "=" .. tostring(value) end
    for _, axis in ipairs({"X", "Y", "Z"}) do
        field(axis:lower(), finite(location and read(location, axis)))
        field("v" .. axis:lower(), finite(velocity and read(velocity, axis)))
        field("camera_" .. axis:lower(), finite(camera_location and read(camera_location, axis)))
    end
    for _, axis in ipairs({"Pitch", "Yaw", "Roll"}) do
        field(axis:lower(), finite(rotation and read(rotation, axis)))
        field("camera_" .. axis:lower(), finite(camera_rotation and read(camera_rotation, axis)))
    end
    for _, property in ipairs({"Health", "Stamina", "Consciousness", "Fallen", "DED"}) do
        local value = pawn and read(pawn, property)
        if type(value) == "number" then field(property:lower(), finite(value)) end
        if type(value) == "boolean" then field(property:lower(), value and "1" or "0") end
    end
    skeleton(pawn and read(pawn,"Mesh"),field)
    capture_tick(pawn,field)
    lines[#lines+1] = "end_seq=" .. seq
    -- A small ring of snapshots plus matching footer lets the relay reject partial writes.
    local file, err = io.open(runtime .. "\\half-sword-state-" .. (seq % 8) .. ".txt", "wb")
    if not file then error(err) end
    local written, write_err = file:write(table.concat(lines, "\n") .. "\n")
    file:close()
    if not written then error(write_err) end
end
local mapping_attempts,mapping_next=0,0
local function guarded_tick()
    local request=io.open(runtime..'/setup-mapping.request','rb')
    if request then
        local session=request:read(128);request:close()
        if session==run_id and type(DumpUSMAP)=='function' and mapping_attempts<3 and os.time()>=mapping_next then
            mapping_attempts=mapping_attempts+1;mapping_next=os.time()+10
            local ok,err=pcall(DumpUSMAP)
            if ok then
                os.remove(runtime..'/setup-mapping.request')
                local result=assert(io.open(runtime..'/setup-mapping.result','wb'))
                result:write('RunId='..run_id..'\nState=generated\n');result:close()
            elseif tostring(err)~=last_error then
                print('[HalfLightBridge] Local mapping generation: '..tostring(err)..'\n')
                last_error=tostring(err)
            end
            if not ok and mapping_attempts==3 then
                local result=io.open(runtime..'/setup-mapping.result','wb')
                if result then result:write('RunId='..run_id..'\nState=error\n');result:close() end
            end
        end
    end
    local ok, err = pcall(tick)
    if not ok and tostring(err) ~= last_error then
        print("[HalfLightBridge] Telemetry error: " .. tostring(err) .. "\n")
        last_error = tostring(err)
    end
end
print("[HalfLightBridge] Loaded read-only player/camera probe.\n")
if type(LoopInGameThreadWithDelay) == "function" then
    LoopInGameThreadWithDelay(100, guarded_tick)
else
    local pending = false
    LoopAsync(100, function()
        if not pending then
            pending = true
            ExecuteInGameThread(function() guarded_tick(); pending = false end)
        end
        return false
    end)
end
