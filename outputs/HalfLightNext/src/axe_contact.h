#pragma once
#include <algorithm>
#include <cmath>
namespace halflight_contact {
struct Vec {double x,y,z;};
inline Vec operator+(Vec a,Vec b){return {a.x+b.x,a.y+b.y,a.z+b.z};}
inline Vec operator-(Vec a,Vec b){return {a.x-b.x,a.y-b.y,a.z-b.z};}
inline Vec operator*(Vec a,double b){return {a.x*b,a.y*b,a.z*b};}
inline double dot(Vec a,Vec b){return a.x*b.x+a.y*b.y+a.z*b.z;}
inline double length(Vec a){return std::sqrt(dot(a,a));}
inline Vec unit(Vec a){const double n=length(a);return n>1e-9?a*(1/n):Vec{0,1,0};}
inline Vec transform(const float* m,Vec p){return {m[0]*p.x+m[1]*p.y+m[2]*p.z+m[3],m[4]*p.x+m[5]*p.y+m[6]*p.z+m[7],m[8]*p.x+m[9]*p.y+m[10]*p.z+m[11]};}
struct Closest {Vec blade,body;double distance;};
inline Closest segments(Vec a,Vec b,Vec c,Vec d) {
    const Vec u=b-a,v=d-c,w=a-c;
    const double aa=dot(u,u),bb=dot(u,v),cc=dot(v,v),dd=dot(u,w),ee=dot(v,w);
    double s=0,t=0;
    if(aa<1e-12)t=cc>1e-12?std::clamp(ee/cc,0.0,1.0):0;
    else if(cc<1e-12)s=std::clamp(-dd/aa,0.0,1.0);
    else {
        const double denom=aa*cc-bb*bb;
        s=denom>1e-12?std::clamp((bb*ee-cc*dd)/denom,0.0,1.0):0;
        t=(bb*s+ee)/cc;
        if(t<0){t=0;s=std::clamp(-dd/aa,0.0,1.0);}
        else if(t>1){t=1;s=std::clamp((bb-dd)/aa,0.0,1.0);}
    }
    const Vec p=a+u*s,q=c+v*t;return {p,q,length(p-q)};
}
struct Contact {bool hit=false;Vec point{},normal{},direction{};double speed=0;unsigned region=0;Vec edge{};};
struct Region {Vec a,b;double radius;};
class Detector {
    Vec previous_a{},previous_b{};double last_time=0,last_hit=-10;bool previous=false,touching=false;
    Region previous_regions[16]{};unsigned previous_count=0;
    void remember(Vec a,Vec b,const Region* regions,unsigned count,double now,bool armed){
        previous_a=a;previous_b=b;last_time=now;previous=armed;previous_count=count;
        for(unsigned i=0;i<count;++i)previous_regions[i]=regions[i];
    }
public:
    void reset(){previous=false;touching=false;last_time=0;previous_count=0;}
    Contact sample(Vec a,Vec b,Vec c,Vec d,double radius,double now,bool armed) {
        const Region region{c,d,radius};return sample_regions(a,b,&region,1,now,armed);
    }
    Contact sample_regions(Vec a,Vec b,const Region* regions,unsigned count,double now,bool armed) {
        Contact result{};if(!count || count>16 || !std::isfinite(now)){reset();return result;}
        const auto finite=[](Vec v){return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z);};
        if(!finite(a) || !finite(b)){reset();return result;}
        double minimum_radius=1;
        for(unsigned i=0;i<count;++i){
            if(!finite(regions[i].a) || !finite(regions[i].b) || !std::isfinite(regions[i].radius) || regions[i].radius<=0 || regions[i].radius>2){reset();return result;}
            minimum_radius=std::min(minimum_radius,regions[i].radius);
        }
        Closest current{};double current_gap=1e30;unsigned best_region=0;
        for(unsigned i=0;i<count;++i){const auto q=segments(a,b,regions[i].a,regions[i].b);const double gap=q.distance-regions[i].radius;
            if(gap<current_gap){current=q;current_gap=gap;best_region=i;}}
        const double dt=now-last_time;
        // Starting inside a body does not latch a hit that never happened.
        // Duplicate callbacks in the same millisecond retain sweep history.
        if(!armed || !previous || previous_count!=count || dt>.25){remember(a,b,regions,count,now,armed);touching=false;return result;}
        if(dt<=0)return result;
        const Vec velocity_a=(a-previous_a)*(1/dt),velocity_b=(b-previous_b)*(1/dt);
        auto best=current;double best_gap=current_gap;
        const auto fraction_along=[](Vec p,Vec start,Vec end){const Vec e=end-start;const double n=dot(e,e);return n>1e-12?std::clamp(dot(p-start,e)/n,0.0,1.0):0;};
        double best_along=fraction_along(current.blade,a,b);
        double travel=std::max(length(a-previous_a),length(b-previous_b));
        for(unsigned i=0;i<count;++i)travel=std::max(travel,std::max(length(regions[i].a-previous_regions[i].a),length(regions[i].b-previous_regions[i].b)));
        const unsigned steps=unsigned(std::clamp(std::ceil(travel/(minimum_radius*.5)),4.0,32.0));
        for(unsigned i=0;i<count;++i){
            const auto& region=regions[i];
            unsigned endpoint=0;
            for(auto candidate:{segments(previous_a,a,region.a,region.b),segments(previous_b,b,region.a,region.b)}){
                const double gap=candidate.distance-region.radius;if(gap<best_gap){best=candidate;best_gap=gap;best_region=i;best_along=endpoint;}++endpoint;
            }
            for(unsigned step=0;step<=steps;++step){const double fraction=double(step)/steps;
                const auto& old=previous_regions[i];
                const Vec body_a=old.a+(region.a-old.a)*fraction,body_b=old.b+(region.b-old.b)*fraction;
                const Vec blade_a=previous_a+(a-previous_a)*fraction,blade_b=previous_b+(b-previous_b)*fraction;
                const auto candidate=segments(blade_a,blade_b,body_a,body_b);
                const double gap=candidate.distance-region.radius;if(gap<best_gap){best=candidate;best_gap=gap;best_region=i;best_along=fraction_along(candidate.blade,blade_a,blade_b);}
            }
        }
        // Use velocity at the contact along the edge, relative to the victim.
        // A fast tip must not turn a nearly stationary hilt touch into a heavy hit.
        const Vec edge=b-a;const double along=best_along;
        const auto& body=regions[best_region];const auto& old=previous_regions[best_region];
        const Vec velocity=velocity_a*(1-along)+velocity_b*along-((body.a-old.a)+(body.b-old.b))*(.5/dt);
        const double speed=length(velocity);
        if(!touching && now-last_hit>=.30 && best_gap<=0 && speed>=.6 && speed<=30) {
            const auto separation=best.blade-best.body;
            result={true,best.blade,length(separation)>1e-6?unit(separation):unit(velocity)*(-1),unit(velocity),speed,best_region,edge};last_hit=now;touching=true;
        }
        if(current_gap>.06)touching=false;
        remember(a,b,regions,count,now,armed);return result;
    }
};
}
