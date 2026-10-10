#pragma once
#include "axe_contact.h"
namespace halflight_contact {
enum ImpactFamily : unsigned {Sword,Knife,Axe,Mace,Polearm,Staff,Hafted};
struct ImpactProfile {unsigned family=0;float mass=1.2f,damage=1,stick=.25f;};
struct Impact {float scale=1,force=1,stick=0;unsigned category=1,type=1,severity=0,move=0;bool interrupt=false,knockdown=false;};
inline Impact impact(const Contact& c,const ImpactProfile& p,Vec edge,float& balance,double elapsed){
    Impact out;
    const double speed=std::clamp(c.speed,0.0,30.0),energy=.5*p.mass*speed*speed;
    const bool head=c.region==2 || c.region==11,arm=c.region>=3 && c.region<=6,leg=c.region>=7 && c.region<=10;
    const bool thrust=dot(unit(edge),c.direction)>.82;
    // Damage can use full cutting speed; body displacement uses capped momentum.
    const double reaction_speed=std::min(speed,10.0),momentum=p.mass*reaction_speed;
    const bool light=p.family==Knife || p.mass<.75;
    const double balance_hit=light?0:std::max(0.0,momentum-4)*(leg?1.35:thrust?.35:.65);
    out.category=(p.family==Mace || p.family==Staff)?18:1;
    out.type=out.category==18?2:1;
    if(thrust && (p.family==Sword || p.family==Knife || p.family==Polearm)){out.category=68;out.type=3;}
    out.scale=float(std::clamp(energy/24*p.damage*(head?1.5:arm?.7:leg?.85:1),.08,3.5));
    out.force=float(std::clamp(momentum/55,.1,light?.12:.55));
    out.severity=light?0:momentum>=16?1:0;
    out.move=momentum>=18 && !light?1:0;
    out.interrupt=(arm && energy>=8) || (!light && momentum>=10);
    if(head && !light && momentum>=12){out.severity=1;out.interrupt=true;}
    balance=std::max(0.f,balance-float(std::max(0.0,elapsed)*30));
    balance+=float(balance_hit);
    out.knockdown=!light && (balance>=100 || (p.mass>=1.5f && leg && momentum>=24));
    if(out.knockdown)balance=0;
    if(energy>=10 && !out.knockdown && (p.family==Axe || out.type==3))out.stick=p.stick;
    return out;
}
}
