-- Reflected weapon-pose observation only. Writes private diagnostic traces.
return function(api,pawn)
    local actor=api.read(pawn,'Weapon R')
    assert(api.valid(actor),'No right-hand weapon')
    local root=api.read(actor,'RootComponent')
    assert(api.valid(root),'Weapon root component missing')
    local function observe()
        local transform=api.call(root,'K2_GetComponentToWorld')
        assert(transform,'Reflected component-world transform getter unavailable')
        local values={}
        for _,field in ipairs({'Translation','Rotation','Scale3D'}) do
            local value=api.read(transform,field)
            local axes=field=='Rotation' and {'X','Y','Z','W'} or {'X','Y','Z'}
            for _,axis in ipairs(axes) do
                local number=tonumber(api.read(value,axis))
                assert(number and number==number and math.abs(number)<1e6,'Invalid '..field..'.'..axis)
                values[#values+1]=number
            end
        end
        local norm=values[4]^2+values[5]^2+values[6]^2+values[7]^2
        assert(math.abs(norm-1)<0.01,'Invalid quaternion length')
        return values
    end
    local initial=observe()
    local path=(HALFLIGHT_ROOT.."/work/lab/guest-weapon-pose-")..os.time()..'.csv'
    local f=assert(io.open(path,'wb'))
    f:write('sequence,world_game_seconds,world_real_seconds,position_x_cm,position_y_cm,position_z_cm,quaternion_x,quaternion_y,quaternion_z,quaternion_w,scale_x,scale_y,scale_z\n');f:close()
    local metadata=assert(io.open(path..'.metadata.txt','wb'))
    metadata:write('format=HalfLightGuestWeaponPose1\nactor='..api.safe_text(actor)..'\nroot='..api.safe_text(root)..'\ncoordinates=Unreal-native world centimetres and quaternion; no host conversion\ninitial='..table.concat(initial,','));metadata:close()
    local M={rows={},sequence=0,last_flush=0,actor=actor,root=root,path=path,deadline=os.time()+60,stopped=false}
    function M:flush()
        if #self.rows==0 then return end
        local f=assert(io.open(self.path,'ab'));f:write(table.concat(self.rows,'\n')..'\n');f:close();self.rows={}
    end
    function M:sample(game,real)
        if self.stopped then return end
        if os.time()>=self.deadline then self:flush();self.stopped=true;return end
        if not api.valid(self.actor) or api.read(pawn,'Weapon R')~=self.actor then return end
        local pose=observe()
        self.sequence=self.sequence+1
        local row={self.sequence,string.format('%.6f',game),string.format('%.6f',real)}
        for _,value in ipairs(pose) do row[#row+1]=string.format('%.9g',value) end
        self.rows[#self.rows+1]=table.concat(row,',')
        if real-self.last_flush>=1 or #self.rows>=240 then self:flush();self.last_flush=real end
    end
    return M
end
