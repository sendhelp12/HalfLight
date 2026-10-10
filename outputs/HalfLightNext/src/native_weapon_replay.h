#pragma once
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>

namespace halflight {
// Independent of game addresses, loaders and hooks. Engine integration must
// resolve a fresh object and establish the actual callback thread separately.
struct alignas(16) Matrix34 { std::array<float,12> values{}; };
static_assert(sizeof(Matrix34)==48 && alignof(Matrix34)==16);
struct ReplayFrame { double seconds; Matrix34 matrix; };
struct CallbackContext {
    std::uint64_t session, object, thread;
    bool object_valid;
    // Optional integration-verified callback owner. Its jobs may migrate across
    // OS threads. The integration must separately validate the write phase.
    std::uint64_t verified_update_owner=0;
};
enum class ReplayState { idle, playing, restoring, finished, invalidated };
struct EngineSink {
    virtual bool apply(const CallbackContext&, const Matrix34&) = 0;
    virtual ~EngineSink() = default;
};
class NativeWeaponReplay {
    ReplayState state_=ReplayState::idle;
    CallbackContext bound_{};
    Matrix34 original_{};
    const ReplayFrame* frames_=nullptr;
    std::size_t count_=0, cursor_=0;
    double start_=0,last_=0;
    bool wrote_=false;
    bool matches(const CallbackContext& context) const {
        const bool execution_matches=bound_.verified_update_owner ?
            context.thread && context.verified_update_owner==bound_.verified_update_owner :
            context.thread==bound_.thread && !context.verified_update_owner;
        return context.object_valid && context.session==bound_.session &&
            context.object==bound_.object && execution_matches;
    }
    static bool finite_matrix(const Matrix34& matrix) {
        for(float value:matrix.values)if(!std::isfinite(value))return false;
        return true;
    }
public:
    ReplayState state() const {return state_;}
    bool arm(const CallbackContext& context, const Matrix34& original,
             const ReplayFrame* frames, std::size_t count, double now) {
        // Must be invoked from an integration-verified engine callback.
        if(state_==ReplayState::playing || state_==ReplayState::restoring ||
           !context.object_valid || !context.session || !context.object || !context.thread ||
           !std::isfinite(now) || !frames || count<2 || count>2048 || !finite_matrix(original))return false;
        if(frames[0].seconds!=0 || frames[count-1].seconds<=0 || frames[count-1].seconds>5)return false;
        for(std::size_t i=0;i<count;++i) {
            if(!std::isfinite(frames[i].seconds) || !finite_matrix(frames[i].matrix) ||
               (i && frames[i].seconds<=frames[i-1].seconds))return false;
            double distance=0;
            for(std::size_t axis=0;axis<3;++axis) {
                double delta=frames[i].matrix.values[axis*4+3]-original.values[axis*4+3];
                distance+=delta*delta;
            }
            if(distance>9)return false;
        }
        bound_=context;original_=original;frames_=frames;count_=count;
        cursor_=0;start_=last_=now;wrote_=false;state_=ReplayState::playing;
        return true;
    }
    void cancel() {if(state_==ReplayState::playing)state_=ReplayState::restoring;}
    void update(const CallbackContext& context,double now,EngineSink& sink) {
        if(state_!=ReplayState::playing && state_!=ReplayState::restoring)return;
        // Never restore through a stale/reused object or restarted session.
        if(!context.object_valid || context.session!=bound_.session || context.object!=bound_.object) {
            state_=ReplayState::invalidated;return;
        }
        if(bound_.verified_update_owner) {
            if(!context.thread || context.verified_update_owner!=bound_.verified_update_owner)return;
        } else if(context.thread!=bound_.thread || context.verified_update_owner)return;
        if(!std::isfinite(now) || now<last_) {state_=ReplayState::restoring;}
        else {last_=now;if(now-start_>=frames_[count_-1].seconds)state_=ReplayState::restoring;}
        if(state_==ReplayState::restoring) {
            if(!wrote_ || sink.apply(context,original_))state_=ReplayState::finished;
            else state_=ReplayState::invalidated;
            return;
        }
        // Skip older samples instead of accumulating simulation latency.
        while(cursor_+1<count_ && frames_[cursor_+1].seconds<=now-start_)++cursor_;
        if(!matches(context) || !sink.apply(context,frames_[cursor_].matrix)) {
            state_=ReplayState::invalidated;return;
        }
        wrote_=true;
    }
};
}
