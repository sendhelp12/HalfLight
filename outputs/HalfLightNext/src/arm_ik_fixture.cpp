#include "arm_ik.h"
#include <cstdio>
using namespace halflight_arm;
int main(){
    V s{0,0,0},e{.25,.1,0},w{.45,.15,0},t{.3,.1,.15};auto a=solve(s,e,w,t);
    if(!a.valid || a.reach_error>1e-6 || length(a.wrist-t)>1e-6 || std::abs(length(a.elbow-s)-length(e-s))>1e-6 || std::abs(length(a.wrist-a.elbow)-length(w-e))>1e-6)return 1;
    auto b=solve(s,e,w,{4,0,0});if(!b.valid || b.reach_error<3 || length(b.wrist-s)>length(e-s)+length(w-e))return 2;
    auto c=solve(s,e,w,s);if(c.valid)return 3;
    float m[12]={1,0,0,0,0,1,0,0,0,0,1,0};rotate_toward(m,{1,0,0},{-1,0,0});if(length(vector(m,{1,0,0})-V{-1,0,0})>1e-6)return 4;
    const float wrist[12]={0,-1,0,.2f,1,0,0,.3f,0,0,1,.4f},holder[12]={1,0,0,.05f,0,0,-1,.02f,0,1,0,-.03f},axe[12]={0,0,1,.7f,0,1,0,.8f,-1,0,0,.9f};
    float inv[12]{},desired[12]{},reconstructed[12]{};inverse_rigid(holder,inv);multiply(axe,inv,desired);multiply(desired,holder,reconstructed);
    for(int i=0;i<12;++i)if(std::abs(reconstructed[i]-axe[i])>1e-6)return 5;
    inverse_rigid(wrist,inv);multiply(wrist,inv,reconstructed);if(!rigid(reconstructed) || length(position(reconstructed))>1e-6)return 6;
    // Clothing may contain non-unit scale. Move it by a rigid anchor delta,
    // preserving its relative transform and allowing exact baseline restoration.
    const float scaled_child[12]={2,0,0,.4f,0,3,0,.5f,0,0,4,.6f};
    float moved[12]{},original_local[12]{},moved_local[12]{};
    anchor_delta(wrist,axe,scaled_child,moved);
    inverse_rigid(wrist,inv);multiply(inv,scaled_child,original_local);
    inverse_rigid(axe,inv);multiply(inv,moved,moved_local);
    for(int i=0;i<12;++i)if(std::abs(original_local[i]-moved_local[i])>1e-6)return 7;
    anchor_delta(axe,wrist,moved,reconstructed);
    for(int i=0;i<12;++i)if(std::abs(reconstructed[i]-scaled_child[i])>1e-6)return 8;
    rotate_axis(moved,{0,1,0},.9);const V column{moved[0],moved[4],moved[8]};
    if(std::abs(length(column)-2)>1e-6 || length(position(moved)-position(axe))<.001)return 9;
    float scaled_parent[12]={.8f,0,0,.2f,0,.9f,0,.3f,0,0,.7f,.4f};
    inverse_affine(scaled_parent,inv);multiply(scaled_parent,inv,reconstructed);
    if(!rigid(reconstructed) || length(position(reconstructed))>1e-6)return 10;
    anchor_delta(scaled_parent,axe,scaled_child,moved);
    inverse_affine(scaled_parent,inv);multiply(inv,scaled_child,original_local);
    inverse_affine(axe,inv);multiply(inv,moved,moved_local);
    for(int i=0;i<12;++i)if(std::abs(original_local[i]-moved_local[i])>1e-6)return 11;
    anchor_delta(axe,scaled_parent,moved,reconstructed);
    for(int i=0;i<12;++i)if(std::abs(reconstructed[i]-scaled_child[i])>1e-6)return 12;
    const V extended{.62,.15,.1};const auto supported=solve_supported(s,e,w,extended,.35);
    if(!supported.valid || length(supported.arm.wrist-extended)>1e-6 || supported.support<=.1 ||
       std::abs(length(supported.arm.elbow-supported.shoulder)-length(e-s))>1e-6 ||
       std::abs(length(supported.arm.wrist-supported.arm.elbow)-length(w-e))>1e-6)return 13;
    if(solve_supported(s,e,w,{4,0,0},.35).valid)return 14;
    const double arm_length=length(e-s)+length(w-e);
    const V wide_swing{.85,.15,.1};const auto wider=solve_supported(s,e,w,wide_swing,arm_length);
    if(solve_supported(s,e,w,wide_swing,.35).valid || !wider.valid || length(wider.arm.wrist-wide_swing)>1e-6 ||
       std::abs(length(wider.arm.elbow-wider.shoulder)-length(e-s))>1e-6 ||
       std::abs(length(wider.arm.wrist-wider.arm.elbow)-length(w-e))>1e-6 || solve_supported(s,e,w,{4,0,0},arm_length).valid)return 20;
    const float camera[12]={1,0,0,.3f,0,1,0,1.6f,0,0,1,-2};
    const float grip_world[12]={1,0,0,.53f,0,1,0,1.4f,0,0,1,-2.6f};
    const double base=1/std::tan(57*3.14159265358979323846/360);
    float presentation[12]{};
    if(!project_presentation(camera,base/1.777,base,57,grip_world,presentation))return 15;
    for(int i=0;i<12;++i)if(std::abs(presentation[i]-grip_world[i])>1e-6)return 16;
    const double wide=1/std::tan(77*3.14159265358979323846/360);
    if(!project_presentation(camera,wide/1.777,wide,57,grip_world,presentation))return 17;
    inverse_rigid(camera,inv);
    for(V point:{V{0,0,0},V{.01,.04,0},V{-.01,-.04,.05}}){
        const V physical=transform(inv,transform(grip_world,point)),shown=transform(inv,transform(presentation,point));
        if(std::abs(wide*physical.x/physical.z-base*shown.x/shown.z)>1e-6 ||
           std::abs(wide*physical.y/physical.z-base*shown.y/shown.z)>1e-6)return 18;
    }
    if(project_presentation(camera,-1,wide,57,grip_world,presentation))return 19;
    // Measured native arm, cross-body grip: the former reach correction pulled
    // the upper arm toward the eye. Shoulder stays behind/below it in both hands.
    const float eye[12]={1,0,0,0,0,1,0,0,0,0,1,0};
    for(double side:{1.0,-1.0}){
        const V shoulder{side*.175,-.206,.186},elbow{side*.239,-.493,.130},hand{side*.284,-.728,.032},grip_target{-side*.1,0,-.4};
        const auto shown=solve_presentation(shoulder,elbow,hand,grip_target,eye,side);
        if(!shown.valid || length(shown.arm.wrist-grip_target)>1e-6 || shown.shoulder.z<.12 || shown.shoulder.y>-.24 ||
           side*shown.shoulder.x<.24 || shown.arm.elbow.y>=grip_target.y || side*(shown.arm.elbow.x-grip_target.x)<=0 ||
           std::abs(length(shown.arm.wrist-shown.arm.elbow)-length(hand-elbow))>1e-6 ||
           std::abs(length(shown.arm.elbow-shown.shoulder)-length(elbow-shoulder)*shown.upper_scale)>1e-6)return 21;
        float upper_matrix[12];std::memcpy(upper_matrix,eye,48);
        rotate_toward(upper_matrix,elbow-shoulder,shown.arm.elbow-shown.shoulder);
        stretch_axis(upper_matrix,shown.arm.elbow-shown.shoulder,shown.upper_scale);
        if(length(vector(upper_matrix,elbow-shoulder)-(shown.arm.elbow-shown.shoulder))>1e-6)return 22;
        // Rotate the whole scenario: camera-relative anchoring must rotate with it.
        const float turned[12]={0,0,1,2,0,1,0,1,-1,0,0,3};
        const auto rotated=solve_presentation(transform(turned,shoulder),transform(turned,elbow),transform(turned,hand),transform(turned,grip_target),turned,side);
        if(!rotated.valid || length(rotated.shoulder-transform(turned,shown.shoulder))>1e-6 ||
           length(rotated.arm.elbow-transform(turned,shown.arm.elbow))>1e-6)return 23;
        if(solve_presentation(shoulder,elbow,hand,{4,0,0},eye,side).valid)return 24;
    }
    // Camera clearance must not shrink the previous supported swing envelope.
    const V forward_shoulder{.2,-.1,-.1},forward_elbow{.25,-.35,-.12},forward_hand{.3,-.57,-.09},long_grip{.2,0,-1.05};
    const double old_limit=length(forward_elbow-forward_shoulder)+length(forward_hand-forward_elbow);
    if(!solve_supported(forward_shoulder,forward_elbow,forward_hand,long_grip,old_limit).valid ||
       !solve_presentation(forward_shoulder,forward_elbow,forward_hand,long_grip,eye,1).valid)return 25;
    const V folded{.24,-.24,.12};
    const auto close=solve_presentation({.24,-.24,.12},{.24,-.54,.12},{.24,-.79,.12},folded,eye,1);
    if(!close.valid || length(close.arm.wrist-folded)>1e-6 || close.shoulder.z<.12)return 26;
    puts("arm_ik_fixture_passed: camera-clear shoulders and outward/down elbows in both hands, exact grip, preserved forearm, bounded upper reach, rotated camera, calibrated projection, outlier refusal, hierarchy/restoration");return 0;
}
