"""Fit fresh native fingers around owned weapon geometry; no captured poses bundled."""
import math,struct

I=[1.,0,0,0,0,1.,0,0,0,0,1.,0]
def pos(m):return tuple(m[i] for i in (3,7,11))
def sub(a,b):return tuple(x-y for x,y in zip(a,b))
def add(a,b):return tuple(x+y for x,y in zip(a,b))
def scale(a,s):return tuple(x*s for x in a)
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def length(a):return math.sqrt(dot(a,a))
def unit(a):return scale(a,1/length(a))
def multiply(a,b):return [sum(a[i*4+k]*b[k*4+j] for k in range(3))+(a[i*4+3] if j==3 else 0) for i in range(3) for j in range(4)]
def inverse(m):
    a,b,c,d,e,f,g,h,i=[m[k] for k in (0,1,2,4,5,6,8,9,10)]
    det=a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g);assert det>1e-6
    rows=((e*i-f*h,c*h-b*i,b*f-c*e),(f*g-d*i,a*i-c*g,c*d-a*f),(d*h-e*g,b*g-a*h,a*e-b*d))
    return [rows[r][k]/det if k<3 else -sum(rows[r][j]*m[j*4+3]/det for j in range(3)) for r in range(3) for k in range(4)]
def placed(m,p):
    out=list(m)
    for i,v in zip((3,7,11),p):out[i]=v
    return out
def rotate_toward(m,a,b):
    a,b=unit(a),unit(b);cos=max(-1,min(1,dot(a,b)));axis=cross(a,b);sin=length(axis)
    if sin<1e-8:
        if cos>0:return list(m)
        axis=unit(cross(a,(1,0,0) if abs(a[0])<.8 else (0,1,0)))
    else:axis=scale(axis,1/sin)
    out=list(m)
    for c in range(3):
        old=tuple(m[i*4+c] for i in range(3));new=add(add(scale(old,cos),scale(cross(axis,old),sin)),scale(axis,dot(axis,old)*(1-cos)))
        for i,v in enumerate(new):out[i*4+c]=v
    return out
def solve(s,e,w,t):
    upper,lower,distance=length(sub(e,s)),length(sub(w,e)),length(sub(t,s));assert upper>.001 and lower>.001 and distance>.00001
    reach=max(abs(upper-lower)+1e-6,min(distance,upper+lower-1e-6));direction=unit(sub(t,s))
    bend=sub(sub(e,s),scale(direction,dot(sub(e,s),direction)))
    if length(bend)<1e-6:bend=cross(direction,(0,1,0) if abs(direction[1])<.8 else (1,0,0))
    bend=unit(bend);along=(upper*upper-lower*lower+reach*reach)/(2*reach);height=math.sqrt(max(0,upper*upper-along*along))
    elbow=add(add(s,scale(direction,along)),scale(bend,height));wrist=add(s,scale(direction,reach))
    assert abs(length(sub(elbow,s))-upper)<1e-6 and abs(length(sub(wrist,elbow))-lower)<1e-6
    return elbow,wrist

def fit(profile,geometry,bones,local,palm_reference,side):
    assert side in ('right','left')
    assert len(palm_reference)==12 and all(math.isfinite(v) for v in palm_reference)
    expected={bone['index']:bone for bone in bones}
    first,last,wrist,holder_index=(10,78,25,45) if side=='right' else (79,132,86,106)
    finger_first,finger_last=wrist+1,holder_index
    records=[expected[i] for i in range(first,last)]
    for record in records:
        i=record['index'];parent=record['parent']
        assert parent==first-1 if i==first else first<=parent<i
    centre_x,_,centre_z=profile['grip_centre_m']
    wood_radius=profile['grip_radius_m'];assert .008<wood_radius<.025
    vertices=[(v[0]*.01,(v[2]+profile['geometry_offset_cm'])*.01,v[1]*.01) for v in geometry['vertices']]
    models={wrist:I}
    for i in range(finger_first,finger_last):models[i]=multiply(models[expected[i]['parent']],local[i])
    # Match anatomical palm axes across rigs; their weapon-helper axes are unrelated.
    index,little=pos(models[finger_first+4]),pos(models[finger_first+16])
    x=unit(sub(index,little));forward=scale(add(index,little),.5)
    y=unit(sub(forward,scale(x,dot(forward,x))));z=cross(x,y)
    holder=[x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0]
    source_palm=palm_reference
    # Fit native fingers in the actual sword frame, retaining the accepted live palm mapping.
    wrist_in_weapon=multiply(source_palm,inverse(holder));original={i:multiply(wrist_in_weapon,m) for i,m in models.items()}
    posed={i:list(m) for i,m in original.items()}
    for a in (finger_first,finger_first+4,finger_first+8,finger_first+12,finger_first+16):
        b,c=a+1,a+2;start,e,w=[pos(original[i]) for i in (a,b,c)]
        band=[]
        # Long blade triangles have no vertices near the grip plane; intersect their edges.
        for tri in range(0,len(geometry['indices']),3):
            face=geometry['indices'][tri:tri+3]
            for ia,ib in zip(face,face[1:]+face[:1]):
                va,vb=vertices[ia],vertices[ib];dy=vb[1]-va[1]
                if abs(dy)<1e-8:continue
                fraction=(start[1]-va[1])/dy
                if 0<=fraction<=1:band.append(add(va,scale(sub(vb,va),fraction)))
        if profile['grip_shape']=='cylinder':rx=rz=wood_radius+.006
        else:
            assert band,'Finger outside measured sword geometry'
            rx=max(abs(v[0]-centre_x) for v in band)+.006;rz=max(abs(v[2]-centre_z) for v in band)+.006
        # Curl around the far face, with clearance for the native finger skin.
        radial=unit((start[0]-centre_x,0,start[2]-centre_z))
        face=-1
        target=(centre_x+face*radial[0]*rx,start[1],centre_z+face*radial[2]*rz)
        if length(sub(target,start))>=length(sub(e,start))+length(sub(w,e)):
            face=1;target=(centre_x+radial[0]*rx,start[1],centre_z+radial[2]*rz)
        new_e,new_w=solve(start,e,w,target)
        posed[a]=rotate_toward(original[a],sub(e,start),sub(new_e,start))
        posed[b]=placed(rotate_toward(original[b],sub(w,e),sub(new_w,new_e)),new_e)
        tangent=unit((face*radial[2]*rx,0,-face*radial[0]*rz))
        posed[c]=placed(rotate_toward(original[c],sub(w,e),tangent),new_w)
    wrist_models={i:multiply(inverse(wrist_in_weapon),m) for i,m in posed.items()}
    closed={i:multiply(inverse(wrist_models[expected[i]['parent']]),wrist_models[i]) for i in range(finger_first,finger_last)}
    socket=list(I);socket[3]=centre_x;socket[11]=centre_z
    return holder,socket,records,closed


def packet(holder,socket,records,closed):
    # Session pointers are supplied by the validated live binding, never saved as defaults.
    data=struct.pack('<II4QII24f',0x32504648,0,0,0,0,0,len(records),1,*(holder+socket))
    for record in records:
        data+=struct.pack('<Ii12f',record['index'],record['parent'],*closed.get(record['index'],I))
    assert len(data)==144+len(records)*56
    return data
