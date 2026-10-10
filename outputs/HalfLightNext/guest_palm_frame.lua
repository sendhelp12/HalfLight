-- Anatomical palm in the weapon frame; shared by live grip and local calibration.
return function(api,pawn,root,side,offset)
    assert(side=='r' or side=='l','Invalid palm side')
    local mesh=api.read(pawn,'Mesh')
    assert(api.valid(mesh) and api.valid(root),'Palm scene unavailable')
    local function vector(bone)
        local p=api.call(mesh,'GetSocketLocation',FName(bone))
        local x,y,z=tonumber(api.read(p,'X')),tonumber(api.read(p,'Y')),tonumber(api.read(p,'Z'))
        assert(x and y and z,'Missing source palm bone: '..bone)
        return {x*.01,z*.01,y*.01}
    end
    local function sub(a,b)return {a[1]-b[1],a[2]-b[2],a[3]-b[3]} end
    local function dot(a,b)return a[1]*b[1]+a[2]*b[2]+a[3]*b[3] end
    local function unit(v)
        local d=math.sqrt(dot(v,v));assert(d>.0001 and d<1e6,'Degenerate palm')
        return {v[1]/d,v[2]/d,v[3]/d}
    end
    local t=assert(api.call(root,'K2_GetComponentToWorld'));local q=api.read(t,'Rotation');local p=api.read(t,'Translation')
    local x,y,z,w=tonumber(api.read(q,'X')),tonumber(api.read(q,'Y')),tonumber(api.read(q,'Z')),tonumber(api.read(q,'W'))
    local px,py,pz=tonumber(api.read(p,'X')),tonumber(api.read(p,'Y')),tonumber(api.read(p,'Z'))
    if not (x and y and z and w and px and py and pz and math.abs(x*x+y*y+z*z+w*w-1)<.001) then return nil end
    local frame={1-2*(y*y+z*z),2*(x*z+y*w),2*(x*y-z*w),px*.01,
        2*(x*z-y*w),1-2*(x*x+y*y),2*(y*z+x*w),pz*.01,
        2*(x*y+z*w),2*(y*z-x*w),1-2*(x*x+z*z),py*.01}
    for row=1,3 do frame[row*4]=frame[row*4]-(offset or 0)*.01*frame[row*4-2] end
    local wrist=vector('hand_'..side);local index=vector('index_01_'..side);local little=vector('pinky_01_'..side)
    x=unit(sub(index,little));y=sub({(index[1]+little[1])/2,(index[2]+little[2])/2,(index[3]+little[3])/2},wrist)
    local d=dot(x,y);y=unit({y[1]-d*x[1],y[2]-d*x[2],y[3]-d*x[3]})
    z={x[2]*y[3]-x[3]*y[2],x[3]*y[1]-x[1]*y[3],x[1]*y[2]-x[2]*y[1]}
    local axes={x,y,z,sub(wrist,{frame[4],frame[8],frame[12]})};local result={}
    for row=1,3 do for col=1,4 do
        local v=axes[col];result[#result+1]=frame[row]*v[1]+frame[4+row]*v[2]+frame[8+row]*v[3]
    end end
    return result
end
