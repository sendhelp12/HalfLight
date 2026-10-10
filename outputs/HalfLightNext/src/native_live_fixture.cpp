#include "native_weapon_live.h"
#include "weapon_slots.h"
#include "lease_guard.h"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>
#include <cstdio>
#include <limits>
using namespace halflight;
struct Sink:EngineSink {unsigned calls=0;Matrix34 last{};bool apply(const CallbackContext&,const Matrix34& m)override {++calls;last=m;return true;}};
int main() {
    halflight_guard::LeaseGuard lease;halflight_guard::Lease packet{0x31534648,42,123,1000};
    assert(!lease.update(nullptr,1,42,123) && lease.update(&packet,100,42,123));
    assert(lease.update(nullptr,999,42,123) && !lease.update(nullptr,1000,42,123));
    packet.expiry=2000;assert(lease.update(&packet,1001,42,123));
    packet.expiry=0;assert(!lease.update(&packet,1002,42,123) && !lease.update(nullptr,1003,42,123));
    unsigned type=99;bool present=false;
    assert(halflight_slots::pose_tag(0x334c4648,2,type,present) && type==0 && present);
    assert(halflight_slots::pose_tag(0x744c4648,2,type,present) && type==1 && !present);
    assert(!halflight_slots::pose_tag(0x354c4648,2,type,present));
    assert(!halflight_slots::pose_tag(0x334c4649,2,type,present));
    assert(halflight_slots::pose_tag(0x364c4648,4,type,present) && type==3 && present);
    assert(halflight_slots::pose_tag(0x524c4648,32,type,present) && type==31 && present);
    assert(halflight_slots::pose_tag(0x924c4648,32,type,present) && type==31 && !present);
    assert(!halflight_slots::pose_tag(0x534c4648,32,type,present));
    assert(halflight_slots::bank_bit(63)==0x8000000000000000ull && halflight_slots::bank_bit(64)==0);
    assert(halflight_slots::valid_bank_mask(halflight_slots::bank_bit(63),64));
    assert(!halflight_slots::valid_bank_mask(halflight_slots::bank_bit(63),63));
    CallbackContext c{1,2,3,true,4},migrated{1,2,5,true,4};Matrix34 original{};
    original.values[0]=original.values[5]=original.values[10]=1;
    Sink sink;NativeWeaponLive live;assert(live.arm(c,original,100));
    LivePose p{1,100,original};p.matrix.values[3]=1;
    live.update(migrated,&p,100.1,sink);assert(sink.calls==1 && sink.last.values[3]==1);
    live.update(c,&p,100.2,sink);assert(sink.calls==1);
    p.sequence=2;p.published=100.2;p.matrix.values[3]=4;
    live.update(c,&p,100.3,sink);assert(sink.calls==1);
    p.matrix.values[3]=std::numeric_limits<float>::quiet_NaN();
    live.update(c,&p,100.3,sink);assert(sink.calls==1);
    p.matrix.values[3]=2;p.published=100.3;
    live.update(c,&p,100.31,sink);assert(sink.calls==2);
    auto wrong=c;wrong.verified_update_owner=99;
    live.update(wrong,&p,101,sink);assert(sink.calls==2);
    live.update(c,&p,101,sink);assert(sink.calls==2 && live.state()==ReplayState::playing);
    p.sequence=3;p.published=101.2;p.matrix.values[3]=1.5f;
    live.update(migrated,&p,101.21,sink);assert(sink.calls==3 && sink.last.values[3]==1.5f);
    live.update(c,&p,103.3,sink);assert(sink.calls==4 && sink.last.values[3]==0 && live.state()==ReplayState::finished);
    NativeWeaponLive restart;assert(restart.arm(c,original,0));
    restart.update(c,nullptr,10,sink);assert(restart.state()==ReplayState::finished && sink.calls==4);
    NativeWeaponLive deleted;assert(deleted.arm(c,original,0));
    auto stale=c;stale.object_valid=false;deleted.update(stale,&p,.1,sink);assert(deleted.state()==ReplayState::invalidated && sink.calls==4);
    NativeWeaponLive session;assert(session.arm(c,original,100,0));
    p={1,161,original};p.matrix.values[3]=1;
    session.update(c,&p,161.1,sink);assert(session.state()==ReplayState::playing && sink.calls==5);
    session.update(c,&p,161.2,sink,false);assert(session.state()==ReplayState::finished && sink.calls==6 && sink.last.values[3]==0);
    NativeWeaponLive bad;assert(!bad.arm(c,original,0,-1));
    NativeWeaponLive follow;assert(follow.arm(c,original,0,0));
    Matrix34 camera=original;camera.values[3]=20;p={1,1,original};p.matrix.values[3]=21;
    follow.update(c,&p,1.1,sink,true,&camera);assert(sink.last.values[3]==21 && follow.state()==ReplayState::playing);
    follow.update(c,&p,1.2,sink,false,&camera);assert(sink.last.values[3]==0 && follow.state()==ReplayState::finished);
    NativeWeaponLive smooth;Sink moving;assert(smooth.arm(c,original,0,0));
    p={1,1,original};smooth.update(c,&p,1,moving);
    p={2,1.016,original};p.matrix.values[3]=1;
    p.matrix.values[0]=0;p.matrix.values[2]=1;p.matrix.values[8]=-1;p.matrix.values[10]=0;
    smooth.update(c,&p,1.016,moving);assert(moving.last.values[3]==0);
    smooth.update(c,&p,1.024,moving);assert(std::abs(moving.last.values[3]-.5)<1e-5 && halflight_arm::rigid(moving.last.values.data()));
    assert(std::abs(moving.last.values[0]-std::sqrt(.5))<1e-5);
    smooth.update(c,&p,1.033,moving);assert(moving.last.values[3]==1);
    const auto settled=moving.calls;smooth.update(c,&p,1.04,moving);assert(moving.calls==settled);
    // A long source stall does not extrapolate, then reconnects at the real pose.
    smooth.update(c,&p,1.4,moving);assert(moving.calls==settled);
    p={3,1.5,original};p.matrix.values[3]=2;smooth.update(c,&p,1.5,moving);assert(moving.last.values[3]==2);
    smooth.update(c,&p,1.51,moving,false);assert(moving.last.values[3]==0 && smooth.state()==ReplayState::finished);
    // Receiving a new packet on every host update must still advance motion.
    NativeWeaponLive matched;Sink paced;assert(matched.arm(c,original,0,0));
    for(unsigned i=1;i<=60;++i){
        const double now=i/60.0;p={i,now,original};p.matrix.values[3]=float(i)/60;
        matched.update(c,&p,now,paced);
    }
    assert(paced.last.values[3]>.95f && paced.last.values[3]<1);
    matched.update(c,&p,1.04,paced);assert(paced.last.values[3]==1);
    // Late packet polling preserves the source timeline instead of adding
    // another full easing interval to each delayed arrival.
    NativeWeaponLive jitter;Sink jitter_sink;assert(jitter.arm(c,original,0,0));
    p={1,1,original};jitter.update(c,&p,1,jitter_sink);
    p={2,1.02,original};p.matrix.values[3]=1;jitter.update(c,&p,1.03,jitter_sink);
    assert(std::abs(jitter_sink.last.values[3]-.5)<1e-5);
    p={3,1.04,original};p.matrix.values[3]=2;jitter.update(c,&p,1.045,jitter_sink);
    assert(std::abs(jitter_sink.last.values[3]-1.25)<1e-5);
    // Full turns and off-axis half-turns must traverse the intermediate angle,
    // not collapse linear matrix axes and snap to the destination.
    for(const auto axis:{halflight_arm::V{1,0,0},halflight_arm::V{0,1,0},halflight_arm::V{0,0,1},halflight_arm::V{-1,1,.3}}){
        for(const double degrees:{0.0,.01,120.0,160.0,179.999,180.0,-160.0}){
            NativeWeaponLive turn;Sink turned;assert(turn.arm(c,original,0,0));
            Matrix34 start=original;halflight_arm::rotate_axis(start.values.data(),{0,0,1},.3);
            p={1,1,start};turn.update(c,&p,1,turned);
            Matrix34 end=start,half=start;
            const double radians=degrees*3.14159265358979323846/180;
            halflight_arm::rotate_axis(end.values.data(),axis,radians);
            halflight_arm::rotate_axis(half.values.data(),axis,radians*.5);
            p={2,1.05,end};turn.update(c,&p,1.075,turned);
            assert(halflight_arm::rigid(turned.last.values.data()));
            for(unsigned i=0;i<12;++i){
                if(std::abs(turned.last.values[i]-half.values[i])>=.0002)std::fprintf(stderr,"turn %.6f axis %.2f %.2f %.2f value %u %.6f wanted %.6f\n",degrees,axis.x,axis.y,axis.z,i,turned.last.values[i],half.values[i]);
                assert(std::abs(turned.last.values[i]-half.values[i])<.0002);
            }
        }
    }
    // A 20 Hz source must continue moving across the entire 50 ms interval.
    NativeWeaponLive slow;Sink slow_sink;assert(slow.arm(c,original,0,0));
    p={1,1,original};slow.update(c,&p,1,slow_sink);
    p={2,1.05,original};p.matrix.values[3]=1;slow.update(c,&p,1.05,slow_sink);
    slow.update(c,&p,1.09,slow_sink);assert(std::abs(slow_sink.last.values[3]-.8)<1e-5);
    slow.update(c,&p,1.095,slow_sink);assert(std::abs(slow_sink.last.values[3]-.9)<1e-5);
    slow.update(c,&p,1.101,slow_sink);assert(slow_sink.last.values[3]==1);
    // Camera translation/rotation update every host frame even without a new
    // source pose, and do not participate in sword interpolation.
    NativeWeaponLive attached;Sink viewed;assert(attached.arm(c,original,0,0));
    p={1,1,original};p.matrix.values[3]=.2f;p.matrix.values[11]=-.5f;
    camera=original;camera.values[3]=20;
    attached.update(c,&p,1,viewed,true,&camera,true);assert(std::abs(viewed.last.values[3]-20.2)<1e-5);
    camera.values[3]=21;camera.values[0]=0;camera.values[2]=1;camera.values[8]=-1;camera.values[10]=0;
    attached.update(c,&p,1.01,viewed,true,&camera,true);
    assert(std::abs(viewed.last.values[3]-20.5)<1e-5 && std::abs(viewed.last.values[11]+.2)<1e-5);
    const auto following=viewed.calls;attached.update(c,&p,1.4,viewed,true,&camera,true);assert(viewed.calls==following);
    attached.update(c,&p,1.41,viewed,false,&camera,true);assert(viewed.last.values[3]==0 && attached.state()==ReplayState::finished);
    NativeWeaponLive main_hand,other_hand;Sink main_sink,other_sink;
    assert(main_hand.arm(c,original,0,0) && other_hand.arm(c,original,0,0));
    p={1,1,original};p.matrix.values[3]=.2f;main_hand.update(c,&p,1,main_sink);
    p.matrix.values[3]=-.3f;other_hand.update(c,&p,1,other_sink);
    assert(main_sink.last.values[3]==.2f && other_sink.last.values[3]==-.3f);
    other_hand.update(c,&p,1.01,other_sink,false);
    assert(other_hand.state()==ReplayState::finished && other_sink.last.values[3]==0 && main_hand.state()==ReplayState::playing);
    main_hand.update(c,&p,1.02,main_sink,false);assert(main_hand.state()==ReplayState::finished && main_sink.last.values[3]==0);
    puts("PASS independent weapons: distinct poses, drop one preserves the other, shutdown restores both");
    puts("PASS live core: fresh stream beyond 30 seconds, lease revocation restores, stale source restores, invalid object refusal");
    puts("PASS smoothing: intermediate host updates, rigid 90-degree turn, endpoint, settled hold, stall/reconnect and stop restoration");
}
