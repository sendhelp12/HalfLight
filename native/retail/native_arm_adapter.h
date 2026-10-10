#pragma once
#include "arm_ik.h"
// Included inside the damage adapter's guarded native-update namespace.
struct HandConfig {
    std::uint32_t magic,pid;std::uint64_t session;
    std::uintptr_t player,proxy,entity;std::uint64_t entity_handle;
    std::uintptr_t skeleton;std::uint64_t skeleton_handle;std::uintptr_t definition;
    std::uint32_t count,shoulder,elbow,wrist,grip,enabled;
};
static_assert(sizeof(HandConfig)==96);
struct HandProjection {
    std::uint32_t magic,pid;std::uint64_t session;
    std::uintptr_t camera,table,transform,transform_table;
    float reference_vertical;std::uint32_t enabled;
};
static_assert(sizeof(HandProjection)==56);
struct GripHeader {
    std::uint32_t magic,pid;std::uint64_t session,skeleton,handle,definition;
    std::uint32_t count,enabled;float holder_from_hand[12],socket_from_axe[12];
};
struct GripBone {std::uint32_t index;std::int32_t parent;float local[12];};
static_assert(sizeof(GripHeader)==144 && sizeof(GripBone)==56);
struct NativeArm {
    using GetModel=const float*(*)(void*,int);
    using SetModel=void(*)(void*,int,const float*,bool);
    static constexpr unsigned capacity=68;
    unsigned first=10,count=68,clavicle=9,wrist_index=25,holder=45,finger_first=26,finger_last=44;
    void left(){first=79;count=53;clavicle=78;wrist_index=86;holder=106;finger_first=87;finger_last=105;}
    HandConfig config{};GripHeader grip{};GripBone bones[capacity]{};bool profile_ready=false;
    HandProjection projection{};
    GetModel get_model=nullptr;SetModel set_model=nullptr;
    alignas(16) float baseline[capacity][12]{},clavicle_baseline[12]{};
    std::atomic<bool> modified{false},allowed{false};std::atomic_flag lock=ATOMIC_FLAG_INIT;
    bool have_target=false;
    std::atomic<unsigned> applications{0},refusals{0},reach_refusals{0};
    std::atomic<float> grip_error{0},shoulder_shift{0},attachment_error{0},max_attachment_error{0};
    std::atomic<unsigned> projection_applications{0},projection_refusals{0};
    std::atomic<float> projection_ratio{1};
    bool presentation(const float* physical,float* output,float* camera_output){
        using namespace halflight_arm;
        if(!projection.enabled){std::memcpy(output,physical,48);return true;}
        std::uintptr_t p=0;float camera[12]{},perspective[16]{};
        const bool verified=projection.magic==0x31504648 && projection.pid==cfg.pid && projection.session==cfg.session &&
            read_at(projection.camera,p) && p==projection.table && read_at(projection.camera+0x38,p) && p==projection.transform &&
            read_at(projection.transform,p) && p==projection.transform_table &&
            read(reinterpret_cast<void*>(projection.transform+0x40),camera,48) &&
            read(reinterpret_cast<void*>(projection.transform+0x80),perspective,64) &&
            std::abs(perspective[14]+1)<.001 && std::abs(perspective[15])<.001 &&
            project_presentation(camera,perspective[0],perspective[5],projection.reference_vertical,physical,output);
        if(verified){std::memcpy(camera_output,camera,48);projection_applications.fetch_add(1);projection_ratio.store(float(perspective[5]*std::tan(projection.reference_vertical*3.14159265358979323846/360)));}
        else projection_refusals.fetch_add(1);
        return verified;
    }
    bool valid(){
        std::uintptr_t p=0;std::uint64_t h=0;
        return config.enabled && config.pid==cfg.pid && config.session==cfg.session && config.count==390 &&
            config.shoulder==first && config.elbow==first+1 && config.wrist==wrist_index && config.grip==holder &&
            read_at(config.player+0x38,p) && p==config.proxy && read_at(config.proxy+0x10,p) && p==config.entity &&
            read_at(config.entity+8,h) && h==config.entity_handle && occupied(config.entity,h) &&
            read_at(config.entity+0x58,h) && h==config.skeleton_handle && read_at(config.skeleton+8,h) && h==config.skeleton_handle &&
            occupied(config.skeleton,h) && read_at(config.skeleton+0x10,p) && p==config.entity &&
            read_at(config.skeleton+0x2b0,p) && p==config.definition;
    }
    bool load_profile(const wchar_t* path){
        using namespace halflight_arm;
        FILE* file=_wfopen(path,L"rb");if(!file)return false;
        bool good=fread(&grip,1,sizeof(grip),file)==sizeof(grip) && fread(bones,1,count*sizeof(GripBone),file)==count*sizeof(GripBone) && fgetc(file)==EOF;fclose(file);
        good=good && grip.magic==0x32504648 && grip.pid==config.pid && grip.session==config.session &&
            grip.skeleton==config.skeleton && grip.handle==config.skeleton_handle && grip.definition==config.definition &&
            grip.count==count && grip.enabled==1 && invertible(grip.holder_from_hand) && rigid(grip.socket_from_axe);
        std::uintptr_t storage=0,elements=0;
        good=good && read_at(config.definition+0x78,storage) && read_at(storage+8,elements);
        std::int16_t clavicle_parent=0;
        good=good && read_at(elements+clavicle*0xd0+0xc6,clavicle_parent) && clavicle_parent==6;
        for(unsigned i=0;good && i<count;++i){
            std::int16_t parent=0;const auto& b=bones[i];
            good=b.index==first+i && (i==0?b.parent==int(clavicle):b.parent>=int(first) && b.parent<int(b.index)) &&
                read_at(elements+b.index*0xd0+0xc6,parent) && parent==b.parent && invertible(b.local);
        }
        profile_ready=good;return good;
    }
    void restore(){
        if(!modified.load() || lock.test_and_set(std::memory_order_acquire))return;
        if(valid() && phase_valid()){
            set_model(reinterpret_cast<void*>(config.skeleton),int(clavicle),clavicle_baseline,true);
            for(unsigned i=0;i<count;++i)set_model(reinterpret_cast<void*>(config.skeleton),int(first+i),baseline[i],true);
            modified.store(false);
        }else if(!valid()){modified.store(false);refusals.fetch_add(1);}
        lock.clear(std::memory_order_release);
    }
    bool apply(const float* axe){
        if(lock.test_and_set(std::memory_order_acquire))return false;
        if(!allowed.load() || !valid() || !profile_ready || modified.load()){refusals.fetch_add(1);lock.clear(std::memory_order_release);return false;}
        using namespace halflight_arm;
        bool good=read(get_model(reinterpret_cast<void*>(config.skeleton),int(clavicle)),clavicle_baseline,48) && invertible(clavicle_baseline);
        for(unsigned i=0;i<count && good;++i){
            good=read(get_model(reinterpret_cast<void*>(config.skeleton),int(first+i)),baseline[i],48);
            for(float f:baseline[i])good=good && std::isfinite(f);
        }
        alignas(16) float world[12]{},posed[capacity][12]{},inverse_holder[12]{},inverse_world[12]{},desired_holder[12]{},desired_wrist[12]{},world_holder[12]{};
        good=good && read(reinterpret_cast<void*>(config.skeleton+0x80),world,48) && invertible(world) && rigid(axe);
        for(unsigned i:{0u,1u,2u,3u,wrist_index-first})good=good && invertible(baseline[i]);
        if(good){
            // Finger animation cannot alter the calibrated grip during a swing.
            inverse_affine(grip.holder_from_hand,inverse_holder);inverse_affine(world,inverse_world);
            float physical_holder[12]{},camera_world[12]{},camera_model[12]{};
            multiply(axe,grip.socket_from_axe,physical_holder);
            good=presentation(physical_holder,world_holder,camera_world);
            if(!good){refusals.fetch_add(1);lock.clear(std::memory_order_release);return false;}
            multiply(inverse_world,world_holder,desired_holder);
            multiply(desired_holder,inverse_holder,desired_wrist);
            const V shoulder=position(baseline[0]),elbow=position(baseline[1]),wrist=position(baseline[wrist_index-first]),target=position(desired_wrist);
            PresentationSolution supported{};
            if(projection.enabled){
                multiply(inverse_world,camera_world,camera_model);
                supported=solve_presentation(shoulder,elbow,wrist,target,camera_model,first==10?1:-1);
            }else{
                const auto original=solve_supported(shoulder,elbow,wrist,target,length(elbow-shoulder)+length(wrist-elbow));
                supported={original.arm,original.shoulder,original.offset,1,original.valid};
            }
            grip_error.store(float(supported.arm.reach_error));shoulder_shift.store(float(supported.valid?length(supported.offset):0));
            good=supported.valid;
            if(!supported.valid)reach_refusals.fetch_add(1);
            if(good){
                const auto solution=supported.arm;have_target=true;
                if(good){
                    std::memcpy(posed,baseline,count*48);
                    position(posed[0],supported.shoulder);
                    rotate_toward(posed[0],elbow-shoulder,solution.elbow-supported.shoulder);
                    stretch_axis(posed[0],solution.elbow-supported.shoulder,supported.upper_scale);
                    rotate_toward(posed[1],wrist-elbow,solution.wrist-solution.elbow);position(posed[1],solution.elbow);
                    std::memcpy(posed[wrist_index-first],desired_wrist,48);position(posed[wrist_index-first],solution.wrist);
                    // Carry clothing/helper bones with their arm anchors.
                    float followed_wrist[12]{};anchor_delta(baseline[1],posed[1],baseline[wrist_index-first],followed_wrist);
                    const V axis=unit(solution.wrist-solution.elbow);double roll=0;
                    for(int c=0;c<3;++c){
                        V a{followed_wrist[c],followed_wrist[4+c],followed_wrist[8+c]},b{posed[wrist_index-first][c],posed[wrist_index-first][4+c],posed[wrist_index-first][8+c]};
                        a=a-axis*dot(a,axis);b=b-axis*dot(b,axis);
                        if(length(a)>.2 && length(b)>.2){a=unit(a);b=unit(b);roll=std::atan2(dot(axis,cross(a,b)),dot(a,b));break;}
                    }
                    for(unsigned i=2;i<count;++i){
                        const unsigned index=first+i;if(index==wrist_index)continue;
                        if(index>=finger_first && index<=finger_last){multiply(posed[bones[i].parent-int(first)],bones[i].local,posed[i]);continue;}
                        if(index==holder){multiply(posed[wrist_index-first],grip.holder_from_hand,posed[i]);continue;}
                        int anchor=bones[i].parent;
                        while(anchor!=int(first) && anchor!=int(first+1) && anchor!=int(first+2) && anchor!=int(first+3) && anchor!=int(wrist_index))anchor=bones[anchor-int(first)].parent;
                        anchor_delta(baseline[anchor-int(first)],posed[anchor-int(first)],baseline[i],posed[i]);
                        if(index==first+2 || index==first+3){
                            // Use absolute roll weights, without accumulating each twist.
                            anchor_delta(baseline[1],posed[1],baseline[i],posed[i]);
                            const double fraction=std::clamp(dot(position(baseline[i])-elbow,unit(wrist-elbow))/length(wrist-elbow),0.0,1.0);
                            rotate_axis(posed[i],axis,roll*fraction);
                        }
                    }
                    for(unsigned i=0;i<count;++i)for(float f:posed[i])good=good && std::isfinite(f);
                    if(good){
                        float posed_clavicle[12]{};std::memcpy(posed_clavicle,clavicle_baseline,48);
                        position(posed_clavicle,position(clavicle_baseline)+supported.offset);
                        set_model(reinterpret_cast<void*>(config.skeleton),int(clavicle),posed_clavicle,true);
                        for(unsigned i=0;i<count;++i)set_model(reinterpret_cast<void*>(config.skeleton),int(first+i),posed[i],true);
                        float written_holder[12]{},actual_holder[12]{};
                        if(read(get_model(reinterpret_cast<void*>(config.skeleton),int(holder)),written_holder,48)){
                            multiply(world,written_holder,actual_holder);
                            const auto error=float(length(position(actual_holder)-position(world_holder)));
                            attachment_error.store(error);if(error>max_attachment_error.load())max_attachment_error.store(error);
                        }
                        modified.store(true);applications.fetch_add(1);
                    }
                }
            }
        }
        if(!good){refusals.fetch_add(1);have_target=false;}lock.clear(std::memory_order_release);return good;
    }
} arm,left_arm;
