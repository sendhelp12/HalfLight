#pragma once
#include "native_weapon_replay.h"
#include "arm_ik.h"
namespace halflight {
struct LivePose { std::uint64_t sequence=0; double published=0; Matrix34 matrix{}; };
class NativeWeaponLive {
    CallbackContext bound_{}; Matrix34 original_{};
    ReplayState state_=ReplayState::idle;
    double start_=0,duration_=30; std::uint64_t sequence_=0; bool wrote_=false;
    Matrix34 shown_{},blend_from_{},blend_to_{};
    double published_=0,blend_start_=0,blend_seconds_=0;bool blending_=false;
    static Matrix34 blend(const Matrix34& from,const Matrix34& to,double amount){
        using namespace halflight_arm;
        if(amount<=0)return from;if(amount>=1)return to;
        Matrix34 out=from;double rotation[9]{};
        for(unsigned r=0;r<3;++r)for(unsigned c=0;c<3;++c)for(unsigned k=0;k<3;++k)
            rotation[r*3+c]+=to.values[r*4+k]*from.values[c*4+k];
        const double cosine=std::clamp((rotation[0]+rotation[4]+rotation[8]-1)*.5,-1.0,1.0);
        V axis{rotation[7]-rotation[5],rotation[2]-rotation[6],rotation[3]-rotation[1]};
        const double angle=std::atan2(length(axis)*.5,cosine);
        if(length(axis)<1e-3 && cosine<0){
            // At a half-turn the antisymmetric terms vanish; recover the axis
            // from the largest diagonal instead of snapping the whole blade.
            unsigned k=0;for(unsigned i=1;i<3;++i)if(rotation[i*3+i]>rotation[k*3+k])k=i;
            double v[3]{};v[k]=std::sqrt(std::max(0.0,(rotation[k*3+k]+1)*.5));
            for(unsigned i=0;i<3;++i)if(i!=k)v[i]=(rotation[i*3+k]+rotation[k*3+i])/(4*v[k]);
            const V recovered{v[0],v[1],v[2]};axis=dot(recovered,axis)<0?recovered*(-1):recovered;
        }
        if(length(axis)>1e-8)rotate_axis(out.values.data(),axis,angle*amount);
        for(unsigned row=0;row<3;++row)out.values[row*4+3]=float(from.values[row*4+3]+(to.values[row*4+3]-from.values[row*4+3])*amount);
        return out;
    }
public:
    ReplayState state() const {return state_;}
    bool arm(const CallbackContext& context,const Matrix34& matrix,double now,double duration=30) {
        if(state_==ReplayState::playing || !context.object_valid || !context.session ||
           !context.object || !context.thread || !context.verified_update_owner || !std::isfinite(now) ||
           !std::isfinite(duration) || duration<0)return false;
        for(float v:matrix.values)if(!std::isfinite(v))return false;
        bound_=context;original_=shown_=matrix;start_=now;duration_=duration;sequence_=0;wrote_=false;blending_=false;published_=0;state_=ReplayState::playing;return true;
    }
    void update(const CallbackContext& context,const LivePose* pose,double now,EngineSink& sink,bool lease_alive=true,const Matrix34* reference=nullptr,bool camera_local=false) {
        if(state_!=ReplayState::playing && state_!=ReplayState::restoring)return;
        if(!context.object_valid || context.session!=bound_.session || context.object!=bound_.object) {
            state_=ReplayState::invalidated;return;
        }
        if(!context.thread || context.verified_update_owner!=bound_.verified_update_owner)return;
        bool expiry=!lease_alive || !std::isfinite(now) || now<start_ || (duration_>0 && now-start_>=duration_);
        if(!pose)expiry=expiry || now-start_>=10;
        // Do not apply poses older than 250 ms. A brief source stall holds the
        // current object without making additional calls; restore after 2 s.
        else if(!std::isfinite(pose->published) || pose->published>now || now-pose->published>2)expiry=true;
        if(expiry)state_=ReplayState::restoring;
        if(state_==ReplayState::restoring) {
            state_=!wrote_ || sink.apply(context,original_)?ReplayState::finished:ReplayState::invalidated;return;
        }
        if(!pose || pose->sequence<sequence_ || now-pose->published>.25)return;
        if(camera_local && (!reference || !halflight_arm::rigid(reference->values.data())))return;
        double distance=0;
        for(float v:pose->matrix.values)if(!std::isfinite(v))return;
        for(unsigned axis=0;axis<3;++axis) {
            const double bound=camera_local?0:(reference?reference->values[axis*4+3]:original_.values[axis*4+3]);
            if(!std::isfinite(bound))return;
            const double d=pose->matrix.values[axis*4+3]-bound;distance+=d*d;
        }
        if(distance>9)return;
        bool progressed=false;
        if(blending_){
            const double amount=std::clamp((now-blend_start_)/blend_seconds_,0.0,1.0);
            shown_=blend(blend_from_,blend_to_,amount);if(amount>=1)blending_=false;
            progressed=true;
        }
        if(pose->sequence>sequence_){
            const double interval=pose->published-published_;
            blending_=duration_==0 && wrote_ && interval>0 && interval<=.1 &&
                halflight_arm::rigid(shown_.values.data()) && halflight_arm::rigid(pose->matrix.values.data());
            // Sample on the issued source clock, so packet polling jitter does
            // not restart easing from a lagging display pose on every frame.
            blend_from_=blending_?blend_to_:shown_;blend_to_=pose->matrix;blend_start_=pose->published;
            // Match slower source frames too; ending at 33 ms causes a
            // visible hold before the next 40-100 ms source pose arrives.
            blend_seconds_=std::clamp(interval,.008,.1);published_=pose->published;sequence_=pose->sequence;
            shown_=blending_?blend(blend_from_,blend_to_,std::clamp((now-blend_start_)/blend_seconds_,0.0,1.0)):pose->matrix;
        }else if(!progressed && !camera_local)return;
        Matrix34 drawn=shown_;
        if(camera_local)halflight_arm::multiply(reference->values.data(),shown_.values.data(),drawn.values.data());
        if(!sink.apply(context,drawn)){state_=ReplayState::invalidated;return;}
        wrote_=true;
    }
};
}
