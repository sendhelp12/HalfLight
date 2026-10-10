#pragma once
#include <algorithm>
#include <cmath>
#include <cstring>
namespace halflight_arm {
struct V {double x,y,z;V operator+(V b)const{return{x+b.x,y+b.y,z+b.z};}V operator-(V b)const{return{x-b.x,y-b.y,z-b.z};}V operator*(double s)const{return{x*s,y*s,z*s};}};
inline double dot(V a,V b){return a.x*b.x+a.y*b.y+a.z*b.z;}
inline V cross(V a,V b){return{a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x};}
inline double length(V a){return std::sqrt(dot(a,a));}
inline V unit(V a){const auto l=length(a);return l>1e-8?a*(1/l):V{0,0,0};}
inline V position(const float* m){return{m[3],m[7],m[11]};}
inline void position(float* m,V p){m[3]=float(p.x);m[7]=float(p.y);m[11]=float(p.z);}
inline V vector(const float* m,V p){return{m[0]*p.x+m[1]*p.y+m[2]*p.z,m[4]*p.x+m[5]*p.y+m[6]*p.z,m[8]*p.x+m[9]*p.y+m[10]*p.z};}
inline V inverse_vector(const float* m,V p){return{m[0]*p.x+m[4]*p.y+m[8]*p.z,m[1]*p.x+m[5]*p.y+m[9]*p.z,m[2]*p.x+m[6]*p.y+m[10]*p.z};}
inline V transform(const float* m,V p){return vector(m,p)+position(m);}
inline V inverse_transform(const float* m,V p){return inverse_vector(m,p-position(m));}
inline void multiply(const float* a,const float* b,float* out){for(int r=0;r<3;++r){for(int c=0;c<3;++c){double v=0;for(int k=0;k<3;++k)v+=a[r*4+k]*b[k*4+c];out[r*4+c]=float(v);}out[r*4+3]=float(a[r*4+3]+a[r*4]*b[3]+a[r*4+1]*b[7]+a[r*4+2]*b[11]);}}
inline bool rigid(const float* m){
    for(int i=0;i<12;++i)if(!std::isfinite(m[i]))return false;
    const V x{m[0],m[4],m[8]},y{m[1],m[5],m[9]},z{m[2],m[6],m[10]};
    return std::abs(length(x)-1)<.02 && std::abs(length(y)-1)<.02 && std::abs(length(z)-1)<.02 &&
        std::abs(dot(x,y))<.02 && std::abs(dot(x,z))<.02 && std::abs(dot(y,z))<.02 && dot(cross(x,y),z)>.98;
}
inline void inverse_rigid(const float* m,float* out){
    for(int r=0;r<3;++r)for(int c=0;c<3;++c)out[r*4+c]=m[c*4+r];
    position(out,vector(out,position(m))*(-1));
}
inline bool invertible(const float* m){
    for(int k=0;k<12;++k)if(!std::isfinite(m[k]))return false;
    const V x{m[0],m[4],m[8]},y{m[1],m[5],m[9]},z{m[2],m[6],m[10]};
    const double determinant=dot(x,cross(y,z));
    return determinant>1e-6 && determinant<64 && length(x)<4 && length(y)<4 && length(z)<4;
}
inline void inverse_affine(const float* m,float* out){
    const double a=m[0],b=m[1],c=m[2],d=m[4],e=m[5],f=m[6],g=m[8],h=m[9],i=m[10];
    const double det=a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g);
    const double rows[9]={e*i-f*h,c*h-b*i,b*f-c*e,f*g-d*i,a*i-c*g,c*d-a*f,d*h-e*g,b*g-a*h,a*e-b*d};
    for(int r=0;r<3;++r)for(int k=0;k<3;++k)out[r*4+k]=float(rows[r*3+k]/det);
    position(out,vector(out,position(m))*(-1));
}
inline void anchor_delta(const float* original,const float* posed,const float* child,float* out){
    float inverse[12]{},delta[12]{};inverse_affine(original,inverse);multiply(posed,inverse,delta);multiply(delta,child,out);
}
// Match world geometry to the human-confirmed first-person projection baseline.
// This affects hand presentation only; the physical axe/contact frame stays intact.
inline bool project_presentation(const float* camera,double px,double py,double reference_vertical,const float* world,float* out){
    if(!rigid(camera) || !invertible(world) || !std::isfinite(px) || !std::isfinite(py) ||
       px<=0 || py<=0 || reference_vertical<35 || reference_vertical>100)return false;
    const double reference=1/std::tan(reference_vertical*3.14159265358979323846/360);
    const double ratio=py/reference;
    if(ratio<.3 || ratio>2.5 || px/py<.25 || px/py>4)return false;
    float inverse[12]{},local[12]{},warped[12]{};
    inverse_rigid(camera,inverse);multiply(inverse,world,local);
    std::memcpy(warped,local,48);
    for(int col=0;col<4;++col){warped[col]=float(warped[col]*ratio);warped[4+col]=float(warped[4+col]*ratio);}
    multiply(camera,warped,out);return invertible(out);
}
inline void rotate_axis(float* m,V axis,double angle){
    axis=unit(axis);const double cosine=std::cos(angle),sine=std::sin(angle);
    for(int c=0;c<3;++c){const V old{m[c],m[4+c],m[8+c]};const V v=old*cosine+cross(axis,old)*sine+axis*(dot(axis,old)*(1-cosine));m[c]=float(v.x);m[4+c]=float(v.y);m[8+c]=float(v.z);}
}
inline void stretch_axis(float* m,V axis,double ratio){
    axis=unit(axis);
    for(int c=0;c<3;++c){const V old{m[c],m[4+c],m[8+c]},v=old+axis*(dot(old,axis)*(ratio-1));m[c]=float(v.x);m[4+c]=float(v.y);m[8+c]=float(v.z);}
}
inline void rotate_toward(float* m,V from,V to){
    from=unit(from);to=unit(to);double cosine=std::clamp(dot(from,to),-1.0,1.0);V axis=cross(from,to);double sine=length(axis);
    if(sine<1e-8){if(cosine>0)return;axis=unit(cross(from,std::abs(from.x)<.8?V{1,0,0}:V{0,1,0}));}else axis=axis*(1/sine);
    for(int c=0;c<3;++c){V old{m[c],m[4+c],m[8+c]};V rotated=old*cosine+cross(axis,old)*sine+axis*(dot(axis,old)*(1-cosine));m[c]=float(rotated.x);m[4+c]=float(rotated.y);m[8+c]=float(rotated.z);}
}
struct Solution {V elbow,wrist;double reach_error;bool valid;};
inline Solution solve(V shoulder,V elbow,V wrist,V target,const V* pole=nullptr,double upper_scale=1){
    const double native_upper=length(elbow-shoulder),upper=native_upper*upper_scale,lower=length(wrist-elbow),distance=length(target-shoulder);
    if(!std::isfinite(distance) || !std::isfinite(upper_scale) || upper_scale<1 || native_upper<.05 || native_upper>.8 || upper>2.4 || lower<.05 || lower>.8 || distance<1e-6)return{};
    const double reach=std::clamp(distance,std::abs(upper-lower)+1e-5,upper+lower-1e-5);const V direction=unit(target-shoulder);
    const V toward=(pole?*pole:elbow)-shoulder;
    V bend=toward-direction*dot(toward,direction);
    if(length(bend)<1e-5)bend=cross(direction,std::abs(direction.y)<.8?V{0,1,0}:V{1,0,0});bend=unit(bend);
    const double along=(upper*upper-lower*lower+reach*reach)/(2*reach),height=std::sqrt(std::max(0.0,upper*upper-along*along));
    return{shoulder+direction*along+bend*height,shoulder+direction*reach,std::abs(distance-reach),true};
}
struct PresentationSolution {Solution arm{};V shoulder{},offset{};double upper_scale=1;bool valid=false;};
inline PresentationSolution solve_presentation(V shoulder,V elbow,V wrist,V target,const float* camera,double side){
    if(!rigid(camera) || (side!=1 && side!=-1))return{};
    // Keep the shoulder behind the eye and below/outside the view. Native arm
    // lengths differ from the source rig: extend the upper arm, not its anchor.
    V anchor=inverse_transform(camera,shoulder);
    anchor.x=side*std::max(.24,side*anchor.x);anchor.y=std::min(-.24,anchor.y);anchor.z=std::max(.12,anchor.z);
    anchor=transform(camera,anchor);
    const double upper=length(elbow-shoulder),lower=length(wrist-elbow),native_distance=length(target-shoulder);
    if(upper<.05 || lower<.05 || !std::isfinite(native_distance) || native_distance>2*(upper+lower))return{};
    const double minimum=std::abs(upper-lower)+.02;
    if(length(target-anchor)<minimum)anchor=anchor+vector(camera,{0,0,2*minimum});
    const double distance=length(target-anchor);
    const double scale=std::max(1.0,(distance-lower+.04)/upper);
    const V offset=anchor-shoulder,pole=transform(camera,{side*.5,-.45,-.4});
    const auto arm=solve(anchor,elbow+offset,wrist+offset,target,&pole,scale);
    return{arm,anchor,offset,scale,arm.valid && arm.reach_error<1e-4};
}
struct SupportedSolution {Solution arm{};V shoulder{},offset{};double support=0;bool valid=false;};
inline SupportedSolution solve_supported(V shoulder,V elbow,V wrist,V target,double limit){
    const auto original=solve(shoulder,elbow,wrist,target);
    if(!original.valid || !std::isfinite(limit) || limit<0)return{};
    // First-person shoulder presentation contributes the missing reach. Keep
    // upper/lower segment lengths intact and keep the hand at the grip socket.
    const V offset=target-original.wrist;const double support=length(offset);
    if(support>limit)return{original,shoulder,{},support,false};
    const auto exact=solve(shoulder+offset,elbow+offset,wrist+offset,target);
    return{exact,shoulder+offset,offset,support,exact.valid && exact.reach_error<1e-4};
}
}
