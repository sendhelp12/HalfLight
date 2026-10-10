// Native incoming damage seed and contact adapter for the owned DevTools build.
// Chains the existing continuous movement callback; does not replace its owner.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wincrypt.h>
#include <atomic>
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cwchar>
#include <cstring>
#include <ctime>
#include <io.h>
#include "native_module_hash.hpp"
#include "axe_contact.h"
#include "combat_impact.h"
#include "lease_guard.h"
#include "input_lock_guard.h"
#include "weapon_slots.h"
using namespace halflight_slots;
namespace {
using namespace halflight_contact;
using Callback=void(*)(void*,void*,void*);
using Update=void(*)(void*);
using GetData=const void*(*)(const void*);
using CopyDamage=void*(*)(void*,const void*);
using Destroy=void(*)(void*);
using TakeDamage=void(*)(void*,const void*);
using ReadEntity=const void*(*)(const void*);
using AssignEntity=void*(*)(void*,const void*);
struct Config {
    std::uint32_t magic,pid;
    std::uintptr_t slot,expected,entity,receiver;
    std::uint64_t handle,session;
    std::uintptr_t update_slot,update_expected,update_receiver,axe_xform;
    std::uint64_t axe_handle;
    std::uintptr_t target_xform;
    std::uint64_t target_handle,entity_handle;
    std::uintptr_t seed_source;
    unsigned char movement_hash[32];
};
using Lease=halflight_guard::Lease;
#pragma pack(push,1)
struct PosePacket {std::uint32_t magic,pid;std::uint64_t session,sequence,published;float matrix[12];};
#pragma pack(pop)
struct Binding {std::uintptr_t entity,receiver;std::uint64_t handle;std::uintptr_t xform;std::uint64_t root_handle,entity_handle;};
struct BindingPacket {std::uint32_t magic,pid;std::uint64_t session,sequence,expiry;Binding target;};
constexpr unsigned max_targets=16;
struct TargetPacket {std::uint32_t magic,pid;std::uint64_t session,sequence,expiry;std::uint32_t count,reserved;Binding targets[max_targets];};
struct TargetState {Binding binding{};Detector detectors[max_banks],guards[max_banks];bool present=false,health_known=false;float health=0,balance=0;unsigned last_weapon=0;std::uint64_t last_dispatch=0,last_parry=0;void reset(){for(auto& detector:detectors)detector.reset();for(auto& guard:guards)guard.reset();balance=0;last_parry=0;}};
static_assert(sizeof(Config)==160 && sizeof(Lease)==24 && sizeof(PosePacket)==80);
static_assert(sizeof(BindingPacket)==80);
static_assert(sizeof(TargetPacket)==808);
Config cfg{};HMODULE own=nullptr;std::uintptr_t game=0,engine=0;
struct WeaponContact {std::uint32_t magic,pid;std::uint64_t session;float a[3],b[3],radius,damage_type;};
static_assert(sizeof(WeaponContact)==48);
WeaponContact weapon_contact{0x31574648,0,0,{-.14003f,.31754f,0},{-.14812f,.37230f,0},0,0};
ImpactProfile impact_profiles[max_banks]{};
bool valid_contact(const WeaponContact& value){
    double distance=0;
    for(unsigned i=0;i<3;++i){
        if(!std::isfinite(value.a[i]) || !std::isfinite(value.b[i]) || std::abs(value.a[i])>4 || std::abs(value.b[i])>4)return false;
        const double delta=value.a[i]-value.b[i];distance+=delta*delta;
    }
    return value.magic==0x31574648 && value.pid==cfg.pid && value.session==cfg.session &&
        std::isfinite(value.radius) && value.radius>=0 && value.radius<.1f && (value.damage_type==0 || value.damage_type==1 || value.damage_type==18) && distance>.0001 && distance<16;
}
#include "native_body_snapshot.h"
Callback original_hit=nullptr;Update original_update=nullptr;GetData get_data=nullptr;
CopyDamage copy_damage=nullptr;Destroy destroy_vector=nullptr,destroy_owner=nullptr;TakeDamage take_damage=nullptr;
ReadEntity read_entity=nullptr;
AssignEntity assign_entity=nullptr;
std::uintptr_t seed_attacker=0;std::uint64_t seed_attacker_handle=0;
void** hit_slot=nullptr;void** update_slot=nullptr;
std::atomic<bool> active{false},lease_live{false},seed_ready{false};
std::atomic<bool> input_armed{false};
std::atomic<bool> two_hand_mode{false};
struct GuestGrip {float socket[12],right_socket[12];std::uint64_t expiry=0;bool enabled=false,left_enabled=false,right_enabled=true;unsigned weapon_index=0;};
GuestGrip guest_grips[max_banks]{};std::atomic_flag grip_lock=ATOMIC_FLAG_INIT;
std::atomic<unsigned> in_flight{0},captured{0},damage_calls{0},contacts{0},phase_refusals{0};
std::atomic<unsigned> blocked_punches{0},imported_seeds{0},lease_misses{0},input_read_misses{0};
std::atomic<unsigned> blocked_enemy_hits{0};
std::atomic<bool> target_available{false};
std::atomic<unsigned> rebinds{0};
std::atomic_flag binding_lock=ATOMIC_FLAG_INIT;
TargetPacket pending_binding{};TargetState targets[max_targets]{};std::uint64_t binding_sequence=0,bound_until=0;
std::atomic<unsigned> target_count{0},seed_invalidations{0};
std::atomic<unsigned> rendered_samples{0},source_pose_mismatches{0},animated_body_samples{0},body_fallback_samples{0};
std::uintptr_t entity_table=0,skeleton_table=0;
std::atomic_flag busy=ATOMIC_FLAG_INIT;
alignas(16) unsigned char seed[0xe0]{};
std::uintptr_t message_header[2]{};
HANDLE mapping=nullptr;const unsigned char* view=nullptr;
HANDLE offhand_mapping=nullptr;const unsigned char* offhand_view=nullptr;
HANDLE free_mapping[2]{};const unsigned char* free_view[2]{};
std::uint64_t bite_released_until[max_banks]{};
std::atomic<unsigned> bite_reach_releases{0};
bool read(const void* address,void* result,std::size_t size){SIZE_T got=0;return address && ReadProcessMemory(GetCurrentProcess(),address,result,size,&got) && got==size;}
template<class T> bool read_at(std::uintptr_t address,T& result){return read(reinterpret_cast<void*>(address),&result,sizeof(result));}
bool target_valid(){
    std::uint64_t value=0;std::uintptr_t owner=0;
    return read_at(cfg.receiver+8,value) && value==cfg.handle && read_at(cfg.receiver+0x10,owner) && owner==cfg.entity &&
        read_at(cfg.entity+8,value) && value==cfg.entity_handle && read_at(cfg.entity+0x58,value) && value==cfg.target_handle &&
        read_at(cfg.target_xform+8,value) && value==cfg.target_handle;
}
bool occupied(std::uintptr_t address,std::uint64_t handle){
    const auto chunk=address&~std::uintptr_t(0x3fff);unsigned char bytes[0x70]{};
    if(!read(reinterpret_cast<void*>(chunk),bytes,sizeof(bytes)))return false;
    std::uint32_t magic=0,world=0,system=0,multiplier=0,shift=0;std::uint16_t capacity=0;
    std::memcpy(&magic,bytes,4);std::memcpy(&world,bytes+4,4);std::memcpy(&system,bytes+8,4);
    std::memcpy(&multiplier,bytes+0x20,4);std::memcpy(&shift,bytes+0x24,4);std::memcpy(&capacity,bytes+0x2e,2);
    if(magic!=0x79534243 || world!=((handle>>28)&63) || system!=((handle>>34)&1023) || address<chunk+0x70)return false;
    const auto index=((address-chunk-0x70)*multiplier)>>(shift&63);const auto offset=0x30+(index/64)*8;
    std::uint64_t bitmap=0;if(index>=capacity || offset+8>sizeof(bytes))return false;std::memcpy(&bitmap,bytes+offset,8);
    return bitmap&(std::uint64_t(1)<<(index%64));
}
bool binding_valid(const Binding& b){
    std::uintptr_t pointer=0;std::uint64_t value=0;
    return read_at(b.receiver,pointer) && pointer==game+0x2469170 && read_at(b.receiver+8,value) && value==b.handle &&
        read_at(b.receiver+0x10,pointer) && pointer==b.entity && read_at(b.entity,pointer) && pointer==entity_table &&
        read_at(b.entity+8,value) && value==b.entity_handle && read_at(b.entity+0x58,value) && value==b.root_handle &&
        read_at(b.xform,pointer) && pointer==skeleton_table && read_at(b.xform+8,value) && value==b.root_handle &&
        occupied(b.receiver,b.handle) && occupied(b.entity,b.entity_handle) && occupied(b.xform,b.root_handle);
}
#include "native_target_health.h"
NativeHealth native_health;
std::atomic<unsigned> dead_target_frames{0},unknown_health_frames{0},health_changes{0};
std::atomic<float> measured_health_loss{0};
struct HealthEvent {std::uint64_t tick,entity;unsigned weapon,kind;float before,after;};
HealthEvent health_events[256]{};unsigned health_event_count=0;
void record_health(const TargetState& target,std::uint64_t tick,unsigned kind,float before,float after){
    if(health_event_count<256)health_events[health_event_count++]={tick,target.binding.entity_handle,target.last_weapon,kind,before,after};
}
bool living_target(TargetState& target,std::uint64_t tick){
    float value=0;
    if(!native_health.read_health(target.binding,value)){unknown_health_frames.fetch_add(1);target.reset();return false;}
    if(!target.health_known)record_health(target,tick,0,value,value);
    else if(std::abs(value-target.health)>.0001f){
        health_changes.fetch_add(1);record_health(target,tick,1,target.health,value);
        if(target.last_dispatch && tick-target.last_dispatch<=1000 && value<target.health)
            measured_health_loss.store(measured_health_loss.load()+target.health-value);
    }
    target.health=value;target.health_known=true;
    if(value<=0){dead_target_frames.fetch_add(1);target.reset();return false;}
    return true;
}
bool seed_owner_valid(){
    std::uint64_t handle=0;
    return seed_ready.load() && seed_attacker && read_at(seed_attacker+8,handle) &&
        handle==seed_attacker_handle && occupied(seed_attacker,handle) &&
        read_entity(seed)==reinterpret_cast<const void*>(seed_attacker);
}
void accept_targets(const TargetPacket& packet,std::uint64_t tick){
    if(packet.sequence<=binding_sequence || packet.expiry<=tick || packet.expiry>tick+3000 || packet.count>max_targets || packet.reserved)return;
    for(auto& target:targets)target.present=false;
    for(unsigned i=0;i<packet.count;++i){
        const auto& b=packet.targets[i];if(!binding_valid(b))continue;
        TargetState* chosen=nullptr;
        for(auto& target:targets)if(target.binding.entity_handle==b.entity_handle && target.binding.handle==b.handle && target.binding.root_handle==b.root_handle){chosen=&target;break;}
        if(!chosen)for(auto& target:targets)if(!target.present && !target.binding.entity_handle){chosen=&target;break;}
        if(!chosen)for(auto& target:targets){
            bool retained=false;
            for(unsigned j=0;j<packet.count;++j)if(packet.targets[j].entity_handle==target.binding.entity_handle){retained=true;break;}
            if(!target.present && !retained){chosen=&target;break;}
        }
        if(!chosen)continue;
        if(chosen->binding.entity_handle!=b.entity_handle || chosen->binding.handle!=b.handle || chosen->binding.root_handle!=b.root_handle){chosen->reset();chosen->health_known=false;chosen->last_dispatch=0;rebinds.fetch_add(1);}
        chosen->binding=b;chosen->present=true;
    }
    unsigned count=0;for(auto& target:targets){if(target.present)++count;else target.reset();}
    target_count.store(count);binding_sequence=packet.sequence;bound_until=packet.expiry;
}
bool phase_valid(){
    std::uintptr_t owner=0,manager=0,lane_owner=0,backup=0;DWORD mode_key=0,lane_key=0;
    if(!read_at(engine+0x180c6f0,owner) || !read_at(owner,manager) || !read_at(manager+8,mode_key) ||
       !read_at(engine+0x180c6f8,lane_owner) || !read_at(lane_owner,lane_key) || mode_key>=1088 || lane_key>=1088)return false;
    const auto mode=reinterpret_cast<std::uintptr_t>(TlsGetValue(mode_key));
    const auto lane=reinterpret_cast<std::uintptr_t>(TlsGetValue(lane_key));
    std::uint64_t first=0;
    return mode<2 && lane && lane<=128 && read_at(manager+0x10+(lane-1)*8,backup) && read_at(backup,first);
}
void destroy_damage(void* value){destroy_vector(static_cast<unsigned char*>(value)+0x80);destroy_owner(static_cast<unsigned char*>(value)+0x58);}
bool copy_owned_seed(const void* source,bool rebind_attacker=false){
    std::uintptr_t old_slot=0,new_slot=0,pool=0;
    if(!read(static_cast<const unsigned char*>(source)+0x70,&old_slot,8) || !old_slot)return false;
    copy_damage(seed,source);
    std::memcpy(&new_slot,seed+0x70,8);std::memcpy(&pool,seed+0x78,8);
    if(!new_slot || !pool || new_slot==old_slot){destroy_damage(seed);return false;}
    if(rebind_attacker){
        std::uint64_t handle=0;
        if(!assign_entity || !read_at(seed_attacker+8,handle) || handle!=seed_attacker_handle || !occupied(seed_attacker,handle)){
            destroy_damage(seed);return false;
        }
        // Respawn replaces the entity; assign only the clone, on the verified native phase.
        assign_entity(seed,reinterpret_cast<const void*>(seed_attacker));
        if(read_entity(seed)!=reinterpret_cast<const void*>(seed_attacker)){destroy_damage(seed);return false;}
    }
    message_header[0]=game+0x2a9d728;message_header[1]=game+0x2a9d9d8;
    captured.fetch_add(1);seed_ready.store(true,std::memory_order_release);return true;
}
alignas(16) unsigned char blade_probe[0x1f0]{};
std::atomic<bool> blade_probe_ready{false};
alignas(16) unsigned char baseline_probe[0x1f0]{};std::atomic<bool> baseline_probe_ready{false};
alignas(16) unsigned char bridge_probe[0x1f0]{};std::atomic<bool> bridge_probe_ready{false};
void capture_damage_probe(const unsigned char* source,unsigned char* output,std::atomic<bool>& ready){
    if(input_armed.load() || ready.load())return;
    alignas(16) unsigned char clone[0xe0]{};copy_damage(clone,source);
    std::uintptr_t slot=0,borrowed=0,container=0,table=0;
    std::memcpy(&slot,clone+0x70,8);std::memcpy(&borrowed,source+0x70,8);
    if(slot && slot!=borrowed && read_at(slot,container) && read_at(container,table) && table==game+0x2709118){
        using Evaluate=const void*(*)(void*);
        const auto calculated=reinterpret_cast<Evaluate>(game+0xa81d30)(reinterpret_cast<void*>(container));
        if(reinterpret_cast<std::uintptr_t>(calculated)==container+0x3a8 && read(calculated,output+0xe0,0x110)){
            std::memcpy(output,source,0xe0);ready.store(true,std::memory_order_release);
        }
    }
    destroy_damage(clone);
}
void import_pending_seed(bool phase_ok){
    if(phase_ok && cfg.seed_source && !seed_ready.load()){
        if(copy_owned_seed(reinterpret_cast<void*>(cfg.seed_source),true))imported_seeds.fetch_add(1);
        cfg.seed_source=0;
    }
}
bool matches_player_melee(const unsigned char* source){
    // Match the actual captured attacker/world and native melee context type.
    // Do not block other actors' damage or any input while forwarding is off.
    return input_armed.load() && seed_ready.load() && !std::memcmp(source,seed,8) &&
        !std::memcmp(source+8,seed+8,4) && !std::memcmp(source+0x20,seed+0x20,4) && !std::memcmp(source+0x58,seed+0x58,2);
}
void hit_callback(void* self,void* sender,void* message){
    in_flight.fetch_add(1);
    bool block=false,player_hit=false;
    if(active.load() && lease_live.load() && !busy.test_and_set(std::memory_order_acquire)) {
        bool known=false;
        for(const auto& target:targets)if(target.present && reinterpret_cast<std::uintptr_t>(self)==target.binding.receiver && binding_valid(target.binding)){known=true;break;}
        if(!known)known=reinterpret_cast<std::uintptr_t>(self)==cfg.receiver && target_valid();
        std::uintptr_t receiver_type=0,receiver_owner=0;std::uint64_t receiver_handle=0;
        const auto receiver=reinterpret_cast<std::uintptr_t>(self);
        player_hit=input_armed.load() && seed_owner_valid() && read_at(receiver,receiver_type) && receiver_type==game+0x2469170 &&
            read_at(receiver+0x10,receiver_owner) && receiver_owner==seed_attacker && read_at(receiver+8,receiver_handle) && occupied(receiver,receiver_handle);
        known=known || player_hit;
        // A setup hit can precede the nearby-target publisher's next scan.
        if(!known && !seed_ready.load())known=read_at(receiver,receiver_type) && receiver_type==game+0x2469170 &&
            read_at(receiver+8,receiver_handle) && occupied(receiver,receiver_handle);
        if(known) {
            const auto data=reinterpret_cast<std::uintptr_t>(get_data(message));
            std::uintptr_t header[3]{};unsigned char source[0xe0]{};
            if(data>=8 && read(reinterpret_cast<void*>(data-8),header,sizeof(header)) &&
               header[0]==game+0x2a9d728 && header[1]==game+0x2a9d9d8 &&
               read(reinterpret_cast<void*>(header[2]),source,sizeof(source))) {
                if(!player_hit && read_entity && read_entity(source)==reinterpret_cast<const void*>(seed_attacker)){if(source[0xd0]==1)capture_damage_probe(source,blade_probe,blade_probe_ready);}
                if(player_hit && (source[0xd0]==1 || source[0xd0]==18 || source[0xd0]==68 || source[0xd0]==71)){
                    const auto attacker=reinterpret_cast<std::uintptr_t>(read_entity(source));const auto now=GetTickCount64();
                    std::uintptr_t attacker_parent=0;std::uint64_t attacker_handle=0;
                    const bool attacker_valid=attacker && read_at(attacker+8,attacker_handle) && occupied(attacker,attacker_handle) && read_at(attacker+0x10,attacker_parent);
                    for(const auto& target:targets){
                        std::uintptr_t target_parent=0;
                        const bool same=attacker==target.binding.entity || (attacker_valid && read_at(target.binding.entity+0x10,target_parent) && target_parent &&
                            (attacker==target_parent || attacker_parent==target_parent));
                        if(target.present && same && target.last_parry && now-target.last_parry<200 && binding_valid(target.binding)){
                            block=true;blocked_enemy_hits.fetch_add(1);break;
                        }
                    }
                } else if(!seed_ready.load() && read_entity && read_entity(source)==reinterpret_cast<const void*>(seed_attacker)) {
                    // Borrowed only inside this original dispatch; retain a native owned copy.
                    copy_owned_seed(reinterpret_cast<void*>(header[2]));
                } else block=seed_owner_valid() && matches_player_melee(source);
            }
        }
        busy.clear(std::memory_order_release);
    }
    if(block){if(!player_hit)blocked_punches.fetch_add(1);}else original_hit(self,sender,message);
    in_flight.fetch_sub(1);
}
bool fresh_pose(PosePacket& packet,const unsigned char* source=nullptr){
    if(!source)source=view;if(!source)return false;
    const LONG before=*reinterpret_cast<const volatile LONG*>(source);if(!before || (before&1))return false;
    MemoryBarrier();std::memcpy(&packet,source+8,sizeof(packet));MemoryBarrier();
    const auto now=GetTickCount64();unsigned tag=0;bool present=false;
    return before==*reinterpret_cast<const volatile LONG*>(source) && (packet.magic==0x314c4648 || packet.magic==0x324c4648 || (pose_tag(packet.magic,max_types,tag,present) && present)) && packet.pid==cfg.pid &&
        packet.session==cfg.session && packet.sequence && packet.published<=now && now-packet.published<=250;
}
#include "native_arm_adapter.h"
#include "native_target_body.h"
struct WeaponBank {std::uint64_t xform,handle;WeaponContact contact;};
WeaponBank weapon_banks[max_banks]{};
struct GripBank {GripHeader right,left;GripBone right_bones[NativeArm::capacity],left_bones[NativeArm::capacity];};
GripBank grip_banks[max_banks]{};unsigned current_weapon=0,bank_count=0,type_count=0;bool dual=false;
using WeaponIndex=BankMask(*)();WeaponIndex weapon_mask=nullptr;
bool select_weapon(unsigned index){
    if(!dual)return true;
    if(index>=bank_count || !(weapon_mask()&(bank_bit(index))))return false;
    if(index!=current_weapon){
        cfg.axe_xform=weapon_banks[index].xform;cfg.axe_handle=weapon_banks[index].handle;weapon_contact=weapon_banks[index].contact;
        arm.grip=grip_banks[index].right;left_arm.grip=grip_banks[index].left;
        std::memcpy(arm.bones,grip_banks[index].right_bones,sizeof(arm.bones));std::memcpy(left_arm.bones,grip_banks[index].left_bones,sizeof(left_arm.bones));
        arm.have_target=false;left_arm.have_target=false;current_weapon=index;
    }
    return true;
}
bool rendered_pose(float* axe,unsigned index=0){
    PosePacket packet{};std::uint64_t handle=0;
    bool fresh=false;
    if(dual){
        const auto* source=index>=type_count?offhand_view:view;
        unsigned type=0;bool present=false;
        fresh=source && fresh_pose(packet,source) && pose_tag(packet.magic,type_count,type,present) && present && type==index%type_count;
    }else fresh=fresh_pose(packet);
    if(!select_weapon(index) || !fresh || !read_at(cfg.axe_xform+8,handle) || handle!=cfg.axe_handle || !occupied(cfg.axe_xform,handle) ||
       !read(reinterpret_cast<void*>(cfg.axe_xform+0x80),axe,48) || !halflight_arm::rigid(axe))return false;
    // Local packets gate freshness; hands/contact still use the drawn world
    // matrix. Only world packets can be directly compared to that matrix.
    bool differs=false;if(packet.magic==0x314c4648)for(unsigned i=0;i<12;++i)differs=differs || std::abs(axe[i]-packet.matrix[i])>.002f;
    if(differs)source_pose_mismatches.fetch_add(1);
    rendered_samples.fetch_add(1);return true;
}
bool free_weapon_packet(unsigned index,PosePacket& free,bool require_bite=false){
    if(!dual || index>=bank_count)return false;
    const unsigned hand=index>=type_count?1:0;
    PosePacket shown{};unsigned type=0;bool present=false;
    const bool valid=free_view[hand] && fresh_pose(shown,hand?offhand_view:view) && fresh_pose(free,free_view[hand]) &&
        free.sequence==shown.sequence && free.magic==shown.magic &&
        pose_tag(free.magic,type_count,type,present) && present && type==index%type_count && halflight_arm::rigid(free.matrix);
    if(!valid)return false;
    if(require_bite){bool different=false;for(unsigned i=0;i<12;++i)different=different || std::abs(free.matrix[i]-shown.matrix[i])>.00001f;return different;}
    return true;
}
bool restore_free_weapon(unsigned index,float* axe,bool require_bite=false){
    PosePacket packet{};float camera[12]{},ignored[12]{},world[12]{};
    if(!free_weapon_packet(index,packet,require_bite) || !arm.presentation(axe,ignored,camera) || !halflight_arm::rigid(camera))return false;
    halflight_arm::multiply(camera,packet.matrix,world);
    if(!halflight_arm::rigid(world))return false;
    // Same guarded native update and hierarchy setter as the movement owner.
    using Setter=void(*)(void*,const float*);
    reinterpret_cast<Setter>(engine+0x446a80)(reinterpret_cast<void*>(cfg.axe_xform),world);
    if(!read(reinterpret_cast<void*>(cfg.axe_xform+0x80),axe,48))return false;
    for(unsigned i=0;i<12;++i)if(std::abs(axe[i]-world[i])>.0001f)return false;
    return true;
}
#include "native_impact_snapshot.h"
#include "native_damage_scale.h"
#include "native_enemy_weapon.h"
#include "native_combat_check.h"
void update_callback(void* self){
    in_flight.fetch_add(1);
    if(reinterpret_cast<std::uintptr_t>(self)==cfg.update_receiver && phase_valid()){arm.restore();left_arm.restore();}
    original_update(self);
    if(reinterpret_cast<std::uintptr_t>(self)!=cfg.update_receiver || busy.test_and_set(std::memory_order_acquire)){in_flight.fetch_sub(1);return;}
    const bool phase_ok=phase_valid();const auto tick=GetTickCount64();
    BodySnapshot bodies{};bodies.magic=0x36444648;bodies.pid=cfg.pid;bodies.session=cfg.session;
    bodies.sequence=++body_sequence;bodies.expiry=tick+500;
    float axes[max_banks][12]{};bool pose_ok[max_banks]{},attacking[max_banks]{};const unsigned weapon_count=dual?bank_count:1;
    GuestGrip grips[max_banks]{};
    if(!grip_lock.test_and_set(std::memory_order_acquire)){std::memcpy(grips,guest_grips,sizeof(grips));grip_lock.clear(std::memory_order_release);}
    const BankMask mask=dual?weapon_mask():1;unsigned drawn=0,right=0,left=0;
    for(unsigned i=0;i<weapon_count;++i)if(mask&(bank_bit(i))){++drawn;right+=unsigned(grips[i].enabled && grips[i].right_enabled);left+=unsigned(grips[i].enabled && grips[i].left_enabled);}
    const bool hands_coherent=drawn<=1 || (drawn==2 && right==1 && left==1);
    for(unsigned index=0;index<weapon_count;++index){
    pose_ok[index]=active.load() && lease_live.load() && phase_ok && input_armed.load() && rendered_pose(axes[index],index);
    const auto& grip=grips[index];
    const bool grip_ok=hands_coherent && grip.enabled && tick<grip.expiry && (!dual || grip.weapon_index==index);
    attacking[index]=grip_ok && ((grip.right_enabled && (GetAsyncKeyState(VK_LBUTTON)&0x8000)) || (!grip.right_enabled && grip.left_enabled && (GetAsyncKeyState(VK_RBUTTON)&0x8000)));
    if(pose_ok[index] && arm.config.enabled && arm.allowed.load()){
        // Movement has already run. Use this frame's drawn axe, not a newer
        // asynchronous packet that movement has not applied yet.
        if(grip_ok){
            if(tick<bite_released_until[index])restore_free_weapon(index,axes[index]);
            bool attached=true;
            if(grip.right_enabled){std::memcpy(arm.grip.socket_from_axe,grip.right_socket,48);attached=arm.apply(axes[index]);}
            if(grip.left_enabled && left_arm.config.enabled){
                std::memcpy(left_arm.grip.socket_from_axe,grip.socket,48);
                left_arm.allowed.store(arm.allowed.load());attached=left_arm.apply(axes[index]) && attached;
            }
            if(!attached && restore_free_weapon(index,axes[index],true)){
                // Release the visual bite, then solve every gripping hand against
                // the same free weapon matrix before this frame is rendered.
                if(grip.right_enabled)arm.restore();if(grip.left_enabled)left_arm.restore();
                if(grip.right_enabled)arm.apply(axes[index]);if(grip.left_enabled)left_arm.apply(axes[index]);
                bite_released_until[index]=tick+600;bite_reach_releases.fetch_add(1);
            }
        }
    }else if(phase_ok)arm.have_target=false;
    }
    if(active.load() && lease_live.load() && phase_ok && !binding_lock.test_and_set(std::memory_order_acquire)){
        const auto packet=pending_binding;binding_lock.clear(std::memory_order_release);
        accept_targets(packet,tick);
    }
    if(seed_ready.load() && !seed_owner_valid()){
        if(phase_ok){destroy_damage(seed);std::memset(seed,0,sizeof(seed));seed_ready.store(false);seed_invalidations.fetch_add(1);}
    }
    import_pending_seed(phase_ok);
    if(phase_ok && seed_ready.load())capture_damage_probe(seed,baseline_probe,baseline_probe_ready);
    const bool target_ok=target_count.load()>0 && bound_until>tick;target_available.store(target_ok);
    if(!active.load() || !lease_live.load() || !target_ok){for(auto& target:targets)target.reset();}
    else if(!phase_ok){phase_refusals.fetch_add(1);for(auto& target:targets)target.reset();}
    else {
        for(auto& target:targets){
            if(!target.present || !living_target(target,tick))continue;
            float body[12]{};bool body_valid=target.present && binding_valid(target.binding) &&
                read(reinterpret_cast<void*>(target.binding.xform+0x80),body,sizeof(body));
            for(float f:body)body_valid=body_valid && std::isfinite(f);
            if(!std::any_of(pose_ok,pose_ok+weapon_count,[](bool valid){return valid;}) || !body_valid){target.reset();continue;}
            const Vec up{body[1],body[5],body[9]},base{body[3],body[7],body[11]};
            const double scale=length(up);
            body_valid=scale>.5 && scale<2;
            // Measured local geometry for the imported weapon, in the same
            // physics-root frame as its rendering and hand socket.
            Region regions[16]{};auto& rig=target_rigs[&target-targets];
            unsigned region_count=body_valid?rig.regions(target.binding.xform,body,regions):0;
            if(region_count)animated_body_samples.fetch_add(1);
            else if(body_valid){regions[0]={base+up*.30,base+up*1.50,.33*scale};region_count=1;body_fallback_samples.fetch_add(1);}
            Region blockers[2]{};const unsigned blocker_count=region_count==12?enemy_weapons.regions(target.binding,blockers):0;
            if(region_count==12)for(unsigned i=0;i<region_count+blocker_count && bodies.count<224;++i){
                const auto& region=i<12?regions[i]:blockers[i-12];
                const Vec delta=region.b-region.a,axis=unit(delta),centre=(region.a+region.b)*.5;
                const double half=length(delta)*.5+region.radius;
                if(length(delta)>.001 && half>region.radius && half<1.8){
                    auto& shape=bodies.shapes[bodies.count++];shape.entity=target.binding.entity_handle;shape.root=target.binding.root_handle;
                    shape.region=i;
                    shape.centre[0]=float(centre.x);shape.centre[1]=float(centre.y);shape.centre[2]=float(centre.z);
                    shape.axis[0]=float(axis.x);shape.axis[1]=float(axis.y);shape.axis[2]=float(axis.z);
                    shape.radius=float(region.radius);shape.half=float(half);
                }
            }
            for(unsigned index=0;index<weapon_count;++index){
            auto& detector=target.detectors[index];if(!pose_ok[index]){detector.reset();continue;}
            const auto& edge=dual?weapon_banks[index].contact:weapon_contact;
            const Vec a=transform(axes[index],{edge.a[0],edge.a[1],edge.a[2]}),b=transform(axes[index],{edge.b[0],edge.b[1],edge.b[2]});
            Region guard_regions[2]{};std::memcpy(guard_regions,blockers,sizeof(blockers));
            for(unsigned i=0;i<blocker_count;++i)guard_regions[i].radius+=edge.radius;
            auto parry=target.guards[index].sample_regions(a,b,guard_regions,blocker_count,tick/1000.0,input_armed.load());
            if(parry.hit){parry.region+=12;target.last_parry=tick;dispatch_contact(target,index,parry,tick);detector.reset();continue;}
            if(target.last_parry && tick-target.last_parry<160){detector.reset();continue;}
            Region expanded[16]{};std::memcpy(expanded,regions,sizeof(regions));for(unsigned i=0;i<region_count;++i)expanded[i].radius+=edge.radius;
            const auto contact=detector.sample_regions(a,b,expanded,region_count,tick/1000.0,seed_owner_valid() && input_armed.load() && attacking[index]);
            if(contact.hit){
                contacts.fetch_add(1);
                dispatch_contact(target,index,contact,tick);
            }
            }
        }
    }
    if(active.load() && lease_live.load() && phase_ok)run_combat_check(tick);
    publish_bodies(bodies);
    busy.clear(std::memory_order_release);in_flight.fetch_sub(1);
}
bool exchange(void** slot,void* desired,void* expected){
    DWORD old=0,discard=0;if(!VirtualProtect(slot,8,PAGE_READWRITE,&old))return false;
    const auto found=InterlockedCompareExchangePointer(reinterpret_cast<void* volatile*>(slot),desired,expected);
    const bool protected_again=VirtualProtect(slot,8,old,&discard)!=0;return found==expected && protected_again;
}
bool decode_grip(const char* grip_text,std::uint64_t session,long long unix,GuestGrip& next,unsigned long long& seq){
        unsigned long long gs=0,end=0;long long expiry=0;int on=0,left_on=0,used=0;
        const int fields=std::sscanf(grip_text,"Session=%16llx\nseq=%llu\nend_seq=%llu\nexpires_at=%lld\nenabled=%d\nleft_enabled=%d\nsocket=%f,%f,%f,%f,%f,%f,%f,%f,%f,%f,%f,%f\nright_socket=%f,%f,%f,%f,%f,%f,%f,%f,%f,%f,%f,%f\n%n",
            &gs,&seq,&end,&expiry,&on,&left_on,&next.socket[0],&next.socket[1],&next.socket[2],&next.socket[3],&next.socket[4],&next.socket[5],&next.socket[6],&next.socket[7],&next.socket[8],&next.socket[9],&next.socket[10],&next.socket[11],
            &next.right_socket[0],&next.right_socket[1],&next.right_socket[2],&next.right_socket[3],&next.right_socket[4],&next.right_socket[5],&next.right_socket[6],&next.right_socket[7],&next.right_socket[8],&next.right_socket[9],&next.right_socket[10],&next.right_socket[11],&used);
        int right_on=1,tail=0;
        if(used && grip_text[used]){
            if(std::sscanf(grip_text+used,"right_enabled=%d\n%n",&right_on,&tail)!=1 || !tail || (right_on!=0 && right_on!=1))return false;
            used+=tail;
            if(grip_text[used]){
                int index=-1;tail=0;
                if(std::sscanf(grip_text+used,"weapon_index=%d\n%n",&index,&tail)!=1 || !tail || (index<0 || index>=int(max_banks)))return false;
                next.weapon_index=unsigned(index);used+=tail;
            }
        }
        const bool complete=fields==30 && used && std::size_t(used)==std::strlen(grip_text) && gs==session && seq && seq==end &&
            expiry>=unix && expiry<=unix+1 && (on==0 || on==1) && (left_on==0 || left_on==1) && halflight_arm::rigid(next.socket) && halflight_arm::rigid(next.right_socket) &&
            halflight_arm::length(halflight_arm::position(next.socket))<1.5 && halflight_arm::length(halflight_arm::position(next.right_socket))<1.5;
        next.enabled=on==1;next.left_enabled=left_on==1;next.right_enabled=right_on==1;return complete;
}
DWORD WINAPI run(void*){
    // One startup worker per pinned module. Long-path buffers belong in module
    // storage: a game-created thread can have only a 1MB reserved stack.
    static wchar_t directory[32768]{};GetModuleFileNameW(own,directory,32768);auto slash=wcsrchr(directory,L'\\');if(!slash)return 1;*slash=0;
    static wchar_t config_path[32768]{},log_path[32768]{},lease_path[32768]{},stop_path[32768]{},input_path[32768]{},binding_path[32768]{},rebind_path[32768]{};
    const DWORD pid=GetCurrentProcessId();
    swprintf(config_path,32768,L"%ls\\native-axe-damage-%lu.config",directory,pid);
    swprintf(log_path,32768,L"%ls\\native-axe-damage-%lu.log",directory,pid);
    swprintf(lease_path,32768,L"%ls\\native-axe-session-%lu.lease",directory,pid);
    swprintf(stop_path,32768,L"%ls\\native-axe-damage-stop-%lu.txt",directory,pid);
    swprintf(rebind_path,32768,L"%ls\\native-axe-rebind-%lu.signal",directory,pid);
    FILE* log=_wfopen(log_path,L"wb");if(!log)return 2;
    FILE* input=_wfopen(config_path,L"rb");bool ok=input && fread(&cfg,1,sizeof(cfg),input)==sizeof(cfg) && fgetc(input)==EOF;if(input)fclose(input);
    static wchar_t image[32768]{};GetModuleFileNameW(nullptr,image,32768);const auto name=wcsrchr(image,L'\\');
    if(!ok || cfg.magic!=0x31444648 || cfg.pid!=pid || !name || _wcsicmp(name+1,L"DyingLightGame_x64_rwdi.exe")){fputs("status,config_refused\n",log);fclose(log);return 3;}
    static wchar_t weapon_path[32768]{};swprintf(weapon_path,32768,L"%ls\\native-weapon-contact-%lu.config",directory,pid);
    FILE* weapon_file=_wfopen(weapon_path,L"rb");
    if(weapon_file){
        ok=fread(&weapon_contact,1,sizeof(weapon_contact),weapon_file)==sizeof(weapon_contact) && fgetc(weapon_file)==EOF;fclose(weapon_file);
        if(!ok || !valid_contact(weapon_contact)){fputs("status,weapon_profile_refused\n",log);fclose(log);return 3;}
    }
    swprintf(input_path,32768,L"%ls\\guest-input-%016llx.txt",directory,static_cast<unsigned long long>(cfg.session));
    swprintf(binding_path,32768,L"%ls\\native-axe-target-%lu.binding",directory,pid);
    static wchar_t body_path[32768]{},body_temporary[32768]{};
    swprintf(body_path,32768,L"%ls\\native-axe-bodies-%lu.snapshot",directory,pid);
    swprintf(body_temporary,32768,L"%ls\\native-axe-bodies-%lu.tmp",directory,pid);
    const auto gm=GetModuleHandleW(L"gamedll_ph_x64_rwdi.dll"),em=GetModuleHandleW(L"engine_x64_rwdi.dll");
    const unsigned char gh[32]={0xb4,0x17,0x21,0x3b,0x3b,0x1e,0x70,0xb9,0xbb,0x58,0x9b,0x88,0xd3,0x88,0xbb,0x99,0xdd,0x21,0x3b,0x90,0x82,0xd4,0x4e,0xf3,0x8f,0x40,0x21,0x14,0x6f,0x6e,0xe6,0xc4};
    const unsigned char eh[32]={0xa0,0x65,0x19,0xee,0x1f,0xd7,0x9d,0xe1,0xd6,0x65,0x21,0x5f,0x38,0xe6,0xb8,0x9f,0x2b,0x07,0x4b,0xf9,0x74,0x59,0x12,0xc6,0x4a,0x6f,0x06,0x84,0x61,0x7a,0xdb,0x63};
    game=reinterpret_cast<std::uintptr_t>(gm);engine=reinterpret_cast<std::uintptr_t>(em);
    const bool empty_target=!cfg.entity && !cfg.receiver && !cfg.handle && !cfg.target_xform && !cfg.target_handle && !cfg.entity_handle;
    if(!gm || !em || !hash_matches(gm,gh) || !hash_matches(em,eh) || cfg.expected!=game+0x2147a80 ||
       cfg.update_slot!=game+0x241eba8+0x3b0 || (!empty_target && !target_valid())){fputs("status,build_or_identity_refused\n",log);fclose(log);return 4;}
    native_health.get=reinterpret_cast<NativeHealth::GetHealth>(game+0x1133ea0);
    if(!empty_target && (!read_at(cfg.entity,entity_table) || !read_at(cfg.target_xform,skeleton_table)))return 4;
    // Chaining is allowed only into our exact resident continuous adapter.
    MEMORY_BASIC_INFORMATION region{};bool known_movement=false;
    if(VirtualQuery(reinterpret_cast<void*>(cfg.update_expected),&region,sizeof(region))){
        static wchar_t module_path[32768]{};
        const auto module=static_cast<HMODULE>(region.AllocationBase);
        if(GetModuleFileNameW(module,module_path,32768)){
            auto split=wcsrchr(module_path,L'\\');
            if(split){*split=0;const auto module_name=split+1;unsigned long long version=0;int consumed=0;
                known_movement=!_wcsicmp(module_path,directory) && swscanf(module_name,L"HalfLightNativeAxeSessionRetail%llu.dll%n",&version,&consumed)==1 &&
                    version && consumed==int(wcslen(module_name)) && hash_matches(module,cfg.movement_hash);
            }
        }
    }
    if(!known_movement){fputs("status,movement_owner_refused\n",log);fclose(log);return 5;}
    unsigned char wrapper[18]{};std::int32_t displacement=0;std::uintptr_t function=0;
    if(!read_at(cfg.expected,wrapper) || wrapper[12]!=0xff || wrapper[13]!=0x15){fputs("status,wrapper_refused\n",log);fclose(log);return 6;}
    std::memcpy(&displacement,wrapper+14,4);if(!read_at(cfg.expected+18+displacement,function))return 7;
    get_data=reinterpret_cast<GetData>(function);original_hit=reinterpret_cast<Callback>(cfg.expected);original_update=reinterpret_cast<Update>(cfg.update_expected);
    copy_damage=reinterpret_cast<CopyDamage>(game+0xc95520);destroy_vector=reinterpret_cast<Destroy>(game+0x20cf60);
    destroy_owner=reinterpret_cast<Destroy>(game+0x1fbdb50);take_damage=reinterpret_cast<TakeDamage>(game+0x2180420);
    read_entity=reinterpret_cast<ReadEntity>(engine+0x4a95d0);
    assign_entity=reinterpret_cast<AssignEntity>(GetProcAddress(reinterpret_cast<HMODULE>(engine),"??4CEntityPointer@cbs@@QEAAAEAV01@PEBVCEntity@1@@Z"));
    enemy_weapons.matrix=reinterpret_cast<NativeEnemyWeapons::GetMatrix>(engine+0x6a0830);
    enemy_weapons.bounds=reinterpret_cast<NativeEnemyWeapons::GetBounds>(engine+0x69c1c0);
    static wchar_t hand_path[32768]{},hand_disable[32768]{};swprintf(hand_path,32768,L"%ls\\native-axe-hand-%lu.config",directory,pid);
    swprintf(hand_disable,32768,L"%ls\\native-axe-hand-disable-%lu.txt",directory,pid);
    input=_wfopen(hand_path,L"rb");
    if(input){
        const bool hand_read=fread(&arm.config,1,sizeof(arm.config),input)==sizeof(arm.config) && fgetc(input)==EOF;fclose(input);
        arm.get_model=reinterpret_cast<NativeArm::GetModel>(engine+0x4d9640);
        arm.set_model=reinterpret_cast<NativeArm::SetModel>(engine+0x4ffc60);
        static wchar_t grip_path[32768]{};swprintf(grip_path,32768,L"%ls\\native-axe-grip-%lu.config",directory,pid);
        if(!hand_read || arm.config.magic!=0x31484648 || !arm.valid() || !arm.load_profile(grip_path))arm.config.enabled=0;
        static wchar_t presentation_path[32768]{};swprintf(presentation_path,32768,L"%ls\\native-axe-presentation-%lu.config",directory,pid);
        FILE* presentation_file=_wfopen(presentation_path,L"rb");
        if(presentation_file){
            if(fread(&arm.projection,1,sizeof(arm.projection),presentation_file)!=sizeof(arm.projection) || fgetc(presentation_file)!=EOF)arm.config.enabled=0;
            fclose(presentation_file);
        }
    }
    left_arm.left();left_arm.config=arm.config;left_arm.config.shoulder=79;left_arm.config.elbow=80;left_arm.config.wrist=86;left_arm.config.grip=106;
    left_arm.get_model=arm.get_model;left_arm.set_model=arm.set_model;left_arm.projection=arm.projection;
    static wchar_t left_path[32768]{};swprintf(left_path,32768,L"%ls\\native-axe-left-grip-%lu.config",directory,pid);
    if(!left_arm.valid() || !left_arm.load_profile(left_path))left_arm.config.enabled=0;
    static wchar_t weapons_path[32768]{};swprintf(weapons_path,32768,L"%ls\\native-weapons-damage-%lu.config",directory,pid);
    FILE* weapons_file=_wfopen(weapons_path,L"rb");
    if(weapons_file){
        fseek(weapons_file,0,SEEK_END);const long bytes=ftell(weapons_file);rewind(weapons_file);
        bank_count=bytes>0?unsigned(bytes/sizeof(WeaponBank)):0;type_count=bank_count/2;
        ok=bank_count>=2 && bank_count<=max_banks && !(bank_count&1) && bytes==long(bank_count*sizeof(WeaponBank)) && fread(weapon_banks,sizeof(WeaponBank),bank_count,weapons_file)==bank_count && fgetc(weapons_file)==EOF;fclose(weapons_file);
        HMODULE movement=nullptr;
        ok=ok && GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,reinterpret_cast<LPCWSTR>(cfg.update_expected),&movement);
        if(ok)weapon_mask=reinterpret_cast<WeaponIndex>(GetProcAddress(movement,"HLF_WeaponMask"));
        ok=ok && weapon_mask && valid_bank_mask(weapon_mask(),bank_count) && arm.config.enabled && left_arm.config.enabled;
        for(unsigned i=0;i<bank_count && ok;++i){
            std::uint64_t handle=0;const auto& bank=weapon_banks[i];
            ok=valid_contact(bank.contact) && read_at(bank.xform+8,handle) && handle==bank.handle && occupied(bank.xform,handle);
            for(unsigned j=0;j<i;++j)ok=ok && bank.xform!=weapon_banks[j].xform;
            static wchar_t bank_path[32768]{};
            swprintf(bank_path,32768,L"%ls\\native-axe-grip-%lu-%u.config",directory,pid,i);ok=ok && arm.load_profile(bank_path);
            swprintf(bank_path,32768,L"%ls\\native-axe-left-grip-%lu-%u.config",directory,pid,i);ok=ok && left_arm.load_profile(bank_path);
            if(ok){grip_banks[i].right=arm.grip;grip_banks[i].left=left_arm.grip;std::memcpy(grip_banks[i].right_bones,arm.bones,sizeof(arm.bones));std::memcpy(grip_banks[i].left_bones,left_arm.bones,sizeof(left_arm.bones));}
        }
        if(!ok){fputs("status,weapon_banks_refused\n",log);fclose(log);return 4;}
        dual=true;current_weapon=bank_count-1;cfg.axe_xform=weapon_banks[current_weapon].xform;cfg.axe_handle=weapon_banks[current_weapon].handle;weapon_contact=weapon_banks[current_weapon].contact;
    }
    static wchar_t impact_path[32768]{};swprintf(impact_path,32768,L"%ls\\native-combat-profiles-%lu.config",directory,pid);
    FILE* impact_file=_wfopen(impact_path,L"rb");
    std::uint64_t impact_header[2]{};const unsigned impact_count=dual?bank_count:1;
    bool impacts_ok=impact_file && fread(impact_header,16,1,impact_file)==1 &&
        impact_header[0]==((std::uint64_t(pid)<<32)|0x31494648) && impact_header[1]==cfg.session &&
        fread(impact_profiles,sizeof(ImpactProfile),impact_count,impact_file)==impact_count && fgetc(impact_file)==EOF;
    if(impact_file)fclose(impact_file);
    for(unsigned i=0;i<impact_count;++i){const auto& p=impact_profiles[i];
        impacts_ok=impacts_ok && p.family<=6 && std::isfinite(p.mass) && p.mass>=.1f && p.mass<=8 &&
            std::isfinite(p.damage) && p.damage>=.1f && p.damage<=4 && std::isfinite(p.stick) && p.stick>=0 && p.stick<=.6f;
    }
    if(!impacts_ok){fputs("status,combat_profiles_refused\n",log);fclose(log);return 4;}
    // Hand posing may start without an enemy. Derive the expected CBS types from
    // the independently verified occupied player rig; incoming targets still
    // require exact type, ownership, occupancy and fresh binding checks.
    if(empty_target && (!arm.valid() || !read_at(arm.config.entity,entity_table) || !read_at(arm.config.skeleton,skeleton_table))){
        fputs("status,empty_target_hand_identity_refused\n",log);fclose(log);return 4;
    }
    if(!arm.valid()){fputs("status,attacker_identity_refused\n",log);fclose(log);return 4;}
    seed_attacker=arm.config.entity;seed_attacker_handle=arm.config.entity_handle;
    hit_slot=reinterpret_cast<void**>(cfg.slot);update_slot=reinterpret_cast<void**>(cfg.update_slot);
    std::uintptr_t value=0;if(cfg.slot%8 || !read_at(cfg.slot,value) || value!=cfg.expected || !read_at(cfg.update_slot,value) || value!=cfg.update_expected){fputs("status,slots_refused\n",log);fclose(log);return 8;}
    wchar_t mapping_name[128]{};swprintf(mapping_name,128,L"Local\\HalfLightAxe-%lu-%016llx",pid,static_cast<unsigned long long>(cfg.session));
    mapping=OpenFileMappingW(FILE_MAP_READ,FALSE,mapping_name);if(mapping)view=static_cast<const unsigned char*>(MapViewOfFile(mapping,FILE_MAP_READ,0,0,128));
    if(!view){fputs("status,pose_mapping_refused\n",log);fclose(log);return 9;}
    if(dual){
        swprintf(mapping_name,128,L"Local\\HalfLightAxe-%lu-%016llx-offhand",pid,static_cast<unsigned long long>(cfg.session));
        offhand_mapping=OpenFileMappingW(FILE_MAP_READ,FALSE,mapping_name);if(offhand_mapping)offhand_view=static_cast<const unsigned char*>(MapViewOfFile(offhand_mapping,FILE_MAP_READ,0,0,128));
        if(!offhand_view){fputs("status,offhand_mapping_refused\n",log);fclose(log);return 9;}
        for(unsigned hand=0;hand<2;++hand){
            swprintf(mapping_name,128,L"Local\\HalfLightAxe-%lu-%016llx%ls-free",pid,static_cast<unsigned long long>(cfg.session),hand?L"-offhand":L"");
            free_mapping[hand]=OpenFileMappingW(FILE_MAP_READ,FALSE,mapping_name);
            if(free_mapping[hand])free_view[hand]=static_cast<const unsigned char*>(MapViewOfFile(free_mapping[hand],FILE_MAP_READ,0,0,128));
            if(!free_view[hand]){fputs("status,free_pose_mapping_refused\n",log);fclose(log);return 9;}
        }
    }
    if(cfg.seed_source){
        struct Transfer {std::uint32_t magic,pid;std::uint64_t session,module,seed,attacker,handle,expires;unsigned char hash[32];};
        static_assert(sizeof(Transfer)==88);Transfer transfer{};
        static wchar_t transfer_path[32768]{};swprintf(transfer_path,32768,L"%ls\\native-axe-seed-transfer-%lu.config",directory,pid);
        FILE* transfer_file=_wfopen(transfer_path,L"rb");
        const bool transfer_read=transfer_file && fread(&transfer,1,sizeof(transfer),transfer_file)==sizeof(transfer) && fgetc(transfer_file)==EOF;
        if(transfer_file)fclose(transfer_file);
        MEMORY_BASIC_INFORMATION seed_region{};static wchar_t source_path[32768]{};bool source_named=false;
        const auto old_module=reinterpret_cast<HMODULE>(transfer.module);
        if(transfer_read && GetModuleFileNameW(old_module,source_path,32768)){
            auto split=wcsrchr(source_path,L'\\');unsigned long long version=0;int consumed=0;
            if(split){*split=0;source_named=!_wcsicmp(source_path,directory) && swscanf(split+1,L"HalfLightNativeAxeDamageRetail%llu.dll%n",&version,&consumed)==1 &&
                version && consumed==int(wcslen(split+1));}
        }
        std::uint64_t vector=0;
        const auto tick=GetTickCount64();
        if(!transfer_read || transfer.magic!=0x31544648 || transfer.pid!=pid || transfer.session!=cfg.session || transfer.seed!=cfg.seed_source ||
           transfer.attacker!=seed_attacker || transfer.handle!=seed_attacker_handle || transfer.expires<=tick || transfer.expires>tick+60000 ||
           !source_named || old_module==own || !hash_matches(old_module,transfer.hash) || !VirtualQuery(reinterpret_cast<void*>(cfg.seed_source),&seed_region,sizeof(seed_region)) ||
           seed_region.AllocationBase!=old_module || !read_at(cfg.seed_source+0x80,vector) || (vector&0xffffffffffff)!=cfg.seed_source+0x88 ||
           !assign_entity || !occupied(seed_attacker,seed_attacker_handle)){
            fputs("status,retained_seed_refused\n",log);fclose(log);return 9;
        }
    }
    HMODULE pin=nullptr;if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,reinterpret_cast<LPCWSTR>(&update_callback),&pin))return 10;
    // Install both exact-owner slots before accepting seed or contact work.
    if(!exchange(hit_slot,reinterpret_cast<void*>(&hit_callback),reinterpret_cast<void*>(original_hit)))return 11;
    if(!exchange(update_slot,reinterpret_cast<void*>(&update_callback),reinterpret_cast<void*>(original_update))){exchange(hit_slot,reinterpret_cast<void*>(original_hit),reinterpret_cast<void*>(&hit_callback));return 12;}
    lease_live.store(true);active.store(true);fputs("status,waiting_for_owned_seed\n",log);fflush(log);
    halflight_guard::LeaseGuard guard;halflight_guard::InputLockGuard input_guard,grip_guards[max_banks];const char* stop_reason="requested";ULONGLONG last_status=0;
    static wchar_t guest_grip_path[32768]{};
    halflight_guard::InputPacket previous_input{};
    bool blade_probe_written=false,baseline_probe_written=false,bridge_probe_written=false;
    while(GetFileAttributesW(stop_path)==INVALID_FILE_ATTRIBUTES){
        if(bridge_probe_ready.load(std::memory_order_acquire) && !bridge_probe_written){
            wchar_t probe_path[32768]{};swprintf(probe_path,32768,L"%ls\\native-bridge-cut-%lu.bin",directory,pid);
            FILE* probe=_wfopen(probe_path,L"wb");if(probe){fwrite(bridge_probe,1,sizeof(bridge_probe),probe);fclose(probe);bridge_probe_written=true;}
        }
        if(baseline_probe_ready.load(std::memory_order_acquire) && !baseline_probe_written){
            wchar_t probe_path[32768]{};swprintf(probe_path,32768,L"%s\\native-baseline-hit-%lu.bin",directory,pid);
            FILE* probe=_wfopen(probe_path,L"wb");if(probe){fwrite(baseline_probe,1,sizeof(baseline_probe),probe);fclose(probe);baseline_probe_written=true;}
        }
        if(blade_probe_ready.load(std::memory_order_acquire) && !blade_probe_written){
            wchar_t probe_path[32768]{};swprintf(probe_path,32768,L"%s\\native-blade-hit-%lu.bin",directory,pid);
            FILE* probe=_wfopen(probe_path,L"wb");if(probe){fwrite(blade_probe,1,sizeof(blade_probe),probe);fclose(probe);blade_probe_written=true;}
        }
        if(GetFileAttributesW(rebind_path)!=INVALID_FILE_ATTRIBUTES){stop_reason="movement_objects_replaced";break;}
        arm.allowed.store(arm.config.enabled && GetFileAttributesW(hand_disable)==INVALID_FILE_ATTRIBUTES);
        Lease lease{};DWORD got=0;const auto now=GetTickCount64();
        HANDLE lease_file=CreateFileW(lease_path,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
        bool readable=false,malformed=false;
        if(lease_file!=INVALID_HANDLE_VALUE){readable=ReadFile(lease_file,&lease,sizeof(lease),&got,nullptr) && got==sizeof(lease);malformed=readable && GetFileSize(lease_file,nullptr)!=sizeof(lease);CloseHandle(lease_file);}
        if(!readable)lease_misses.fetch_add(1);
        if(malformed || !guard.update(readable?&lease:nullptr,now,pid,cfg.session)){stop_reason=malformed?"malformed_lease":"lease_invalid_or_expired";break;}
        TargetPacket packet{};HANDLE binding_file=CreateFileW(binding_path,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
        bool valid_packet=false;
        if(binding_file!=INVALID_HANDLE_VALUE){valid_packet=ReadFile(binding_file,&packet,sizeof(packet),&got,nullptr) && got==sizeof(packet) && GetFileSize(binding_file,nullptr)==sizeof(packet);CloseHandle(binding_file);}
        if(valid_packet && packet.magic==0x33444648 && packet.count<=max_targets && !packet.reserved && packet.pid==pid && packet.session==cfg.session && packet.sequence &&
           packet.expiry>now && packet.expiry<=now+3000 && !binding_lock.test_and_set(std::memory_order_acquire)){
            if(packet.sequence>pending_binding.sequence)pending_binding=packet;
            binding_lock.clear(std::memory_order_release);
        }
        char controls[512]{};DWORD control_bytes=0;
        HANDLE control_file=CreateFileW(input_path,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
        const bool controls_read=control_file!=INVALID_HANDLE_VALUE && ReadFile(control_file,controls,sizeof(controls)-1,&control_bytes,nullptr) &&
            control_bytes>0 && GetFileSize(control_file,nullptr)==control_bytes;
        if(control_file!=INVALID_HANDLE_VALUE)CloseHandle(control_file);
        halflight_guard::InputPacket decoded{};const auto unix=std::time(nullptr);
        const bool complete=controls_read && halflight_guard::parse_input(controls,cfg.session,unix,decoded);
        if(complete)previous_input=decoded;else input_read_misses.fetch_add(1);
        const bool armed=input_guard.update(complete,decoded.sequence,decoded.enabled==1,now) && unix<=previous_input.expiry;
        input_armed.store(armed);
        for(unsigned index=0;index<(dual?bank_count:1u);++index){
        if(dual)swprintf(guest_grip_path,32768,L"%ls\\guest-grip-%016llx-%u.txt",directory,static_cast<unsigned long long>(cfg.session),index);
        else swprintf(guest_grip_path,32768,L"%ls\\guest-grip-%016llx.txt",directory,static_cast<unsigned long long>(cfg.session));
        char grip_text[2048]{};FILE* grip_file=_wfopen(guest_grip_path,L"rb");
        if(grip_file){fread(grip_text,1,sizeof(grip_text)-1,grip_file);fclose(grip_file);}
        unsigned long long seq=0;GuestGrip next{};
        const bool grip_complete=decode_grip(grip_text,cfg.session,unix,next,seq) && (!dual || next.weapon_index==index);
        const bool left_on=next.left_enabled,right_on=next.right_enabled;
        next.enabled=grip_guards[index].update(grip_complete,seq,next.enabled,now) && armed;
        next.left_enabled=next.enabled && left_on;next.right_enabled=next.enabled && right_on;next.expiry=now+250;
        if(!grip_lock.test_and_set(std::memory_order_acquire)){
            auto& grip=guest_grips[index];if(grip_complete)grip=next;else {grip.enabled=grip.enabled && next.enabled;grip.left_enabled=grip.left_enabled && next.enabled;grip.right_enabled=grip.right_enabled && next.enabled;}
            grip_lock.clear(std::memory_order_release);
        }
        }
        bool two_hand=false;for(const auto& grip:guest_grips)two_hand=two_hand || (grip.enabled && grip.left_enabled && grip.right_enabled);
        two_hand_mode.store(armed && two_hand);
        write_bodies(body_path,body_temporary);
        CombatCheck check{};bool check_read=false;
        if(!armed){
            static wchar_t check_path[32768]{};swprintf(check_path,32768,L"%ls\\native-combat-check-%lu-%016llx.config",directory,pid,static_cast<unsigned long long>(cfg.session));
            FILE* check_file=_wfopen(check_path,L"rb");
            if(check_file){check_read=fread(&check,1,sizeof(check),check_file)==sizeof(check) && fgetc(check_file)==EOF;fclose(check_file);}
        }
        CombatResult result{};
        // Disk I/O stays on the worker. The callback records only bounded events.
        if(!busy.test_and_set(std::memory_order_acquire)){
            if(check_read && check.magic==0x31434648 && check.pid==pid && check.session==cfg.session &&
               check.sequence>pending_check.sequence && check.expiry>now && check.expiry<=now+30000 && check.kind<=8 && check.bank<(dual?bank_count:1u))pending_check=check;
            result=check_result;
            HealthEvent events[256]{};const auto count=health_event_count;
            std::memcpy(events,health_events,count*sizeof(HealthEvent));health_event_count=0;
            const auto latest_impact=impact_sequence;auto impacts=impact_snapshot;impacts.magic=0x32494648;impacts.pid=pid;impacts.session=cfg.session;
            busy.clear(std::memory_order_release);
            static wchar_t impact_output[32768]{},impact_tmp[32768]{};
            swprintf(impact_output,32768,L"%ls\\native-combat-impacts-%lu.snapshot",directory,pid);
            swprintf(impact_tmp,32768,L"%ls\\native-combat-impacts-%lu.tmp",directory,pid);
            static std::uint64_t published_impact=~std::uint64_t(0);
            if(latest_impact!=published_impact){
            HANDLE impact_out=CreateFileW(impact_tmp,GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_DELETE,nullptr,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);
            if(impact_out!=INVALID_HANDLE_VALUE){DWORD written=0;const bool good=WriteFile(impact_out,&impacts,sizeof(impacts),&written,nullptr) && written==sizeof(impacts);CloseHandle(impact_out);if(good && MoveFileExW(impact_tmp,impact_output,MOVEFILE_REPLACE_EXISTING))published_impact=latest_impact;}
            }
            static wchar_t health_path[32768]{};swprintf(health_path,32768,L"%ls\\native-combat-health-%lu-%016llx.csv",directory,pid,static_cast<unsigned long long>(cfg.session));
            FILE* health_log=count?_wfopen(health_path,L"ab"):nullptr;
            if(health_log){
                fseek(health_log,0,SEEK_END);
                if(ftell(health_log)==0)fputs("tick,entity,weapon_bank,event,health_before,health_after\n",health_log);
                for(unsigned i=0;i<count;++i){const auto& e=events[i];fprintf(health_log,"%llu,%016llx,%u,%s,%.6f,%.6f\n",static_cast<unsigned long long>(e.tick),static_cast<unsigned long long>(e.entity),e.weapon,e.kind==0?"observed":(e.kind==1?"health_change":"dispatch"),e.before,e.after);}
                fclose(health_log);
            }
        }
        static std::uint64_t published_check=0;
        if(result.sequence>published_check){
            static wchar_t result_path[32768]{},result_tmp[32768]{};
            swprintf(result_path,32768,L"%ls\\native-combat-check-%lu-%016llx.result",directory,pid,static_cast<unsigned long long>(cfg.session));
            swprintf(result_tmp,32768,L"%ls\\native-combat-check-%lu-%016llx.tmp",directory,pid,static_cast<unsigned long long>(cfg.session));
            FILE* result_file=_wfopen(result_tmp,L"wb");
            if(result_file){fprintf(result_file,"Session=%016llx\nsequence=%llu\nstatus=%u\nhealth_before=%.6f\nhealth_after=%.6f\n",static_cast<unsigned long long>(cfg.session),static_cast<unsigned long long>(result.sequence),result.status,result.before,result.after);fclose(result_file);
                if(MoveFileExW(result_tmp,result_path,MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH))published_check=result.sequence;}
        }
        // Only this worker writes the log; game callbacks publish counters.
        if(now-last_status>=500){
            rewind(log);fprintf(log,"status,%s\nseed_copies,%u\ncontacts,%u\nnative_damage_calls,%u\nphase_refusals,%u\nblocked_punches,%u\nimported_seeds,%u\nlease_misses,%u\ninput_read_misses,%u\ninput_armed,%u\ntarget_rebinds,%u\nhand_enabled,%u\nhand_applications,%u\nhand_refusals,%u\nhand_reach_refusals,%u\nhand_reach_error_m,%.4f\nnearby_targets,%u\nseed_invalidations,%u\nrendered_pose_samples,%u\nnewer_source_pose_frames,%u\nanimated_body_samples,%u\nroot_body_fallback_samples,%u\nhand_shoulder_shift_m,%.4f\nhand_attachment_error_m,%.6f\nhand_max_attachment_error_m,%.6f\nhand_projection_applications,%u\nhand_projection_refusals,%u\nhand_projection_ratio,%.6f\n",
                !target_available.load()?"waiting_for_target":(seed_ready.load()?"axe_damage_active":"waiting_for_owned_seed"),captured.load(),contacts.load(),damage_calls.load(),phase_refusals.load(),blocked_punches.load(),imported_seeds.load(),lease_misses.load(),input_read_misses.load(),input_armed.load()?1u:0u,rebinds.load(),arm.config.enabled,arm.applications.load(),arm.refusals.load(),arm.reach_refusals.load(),arm.grip_error.load(),target_count.load(),seed_invalidations.load(),rendered_samples.load(),source_pose_mismatches.load(),animated_body_samples.load(),body_fallback_samples.load(),arm.shoulder_shift.load(),arm.attachment_error.load(),arm.max_attachment_error.load(),arm.projection_applications.load(),arm.projection_refusals.load(),arm.projection_ratio.load());
            fflush(log);_chsize(_fileno(log),ftell(log));last_status=now;
            fprintf(log,"blocked_enemy_hits,%u\nenemy_weapon_regions,%u\ncontact_region,%u\nbite_reach_releases,%u\n",blocked_enemy_hits.load(),last_enemy_weapon_regions.load(),last_contact_region.load(),bite_reach_releases.load());
            fprintf(log,"two_hand_mode,%u\nleft_hand_enabled,%u\nleft_hand_applications,%u\nleft_hand_reach_refusals,%u\nleft_hand_attachment_error_m,%.6f\n",two_hand_mode.load()?1u:0u,left_arm.config.enabled,left_arm.applications.load(),left_arm.reach_refusals.load(),left_arm.attachment_error.load());fflush(log);
            fprintf(log,"weapon_mask,%llu\n",static_cast<unsigned long long>(dual?weapon_mask():1u));fflush(log);
            fprintf(log,"dead_target_frames,%u\nunknown_health_frames,%u\nhealth_changes,%u\nmeasured_health_loss,%.6f\n",dead_target_frames.load(),unknown_health_frames.load(),health_changes.load(),measured_health_loss.load());fflush(log);
            fprintf(log,"contact_speed_mps,%.6f\ncontact_damage_scale,%.6f\ncontact_input_coefficient,%.6f\n",last_contact_speed.load(),last_contact_scale.load(),last_contact_coefficient.load());fflush(log);
        }
        Sleep(20);
    }
    active.store(false);lease_live.store(false);
    // Restoration uses the same verified callback phase, never this worker.
    while(arm.modified.load() || left_arm.modified.load())Sleep(1);
    const bool hit_restored=exchange(hit_slot,reinterpret_cast<void*>(original_hit),reinterpret_cast<void*>(&hit_callback));
    const bool update_restored=exchange(update_slot,reinterpret_cast<void*>(original_update),reinterpret_cast<void*>(&update_callback));
    const auto drain=GetTickCount64()+1000;while(in_flight.load() && GetTickCount64()<drain)Sleep(1);
    // Retain at most one owned seed in the pinned module until process exit.
    // Its destruction must not run from this unrelated worker thread.
    if(!in_flight.load()){
        UnmapViewOfFile(view);CloseHandle(mapping);view=nullptr;
        if(offhand_view){UnmapViewOfFile(offhand_view);offhand_view=nullptr;}
        if(offhand_mapping){CloseHandle(offhand_mapping);offhand_mapping=nullptr;}
        for(unsigned hand=0;hand<2;++hand){if(free_view[hand])UnmapViewOfFile(free_view[hand]);if(free_mapping[hand])CloseHandle(free_mapping[hand]);free_view[hand]=nullptr;free_mapping[hand]=nullptr;}
    }
    rewind(log);fprintf(log,"status,stopped\nstop_reason,%s\nhit_callback_restored,%d\nmovement_callback_restored,%d\nseed_copies,%u\nnative_damage_calls,%u\nblocked_punches,%u\nseed_retained_until_exit,%d\ncomplete,1\n",stop_reason,hit_restored?1:0,update_restored?1:0,captured.load(),damage_calls.load(),blocked_punches.load(),seed_ready.load()?1:0);
    fflush(log);_chsize(_fileno(log),ftell(log));fclose(log);return hit_restored && update_restored?0:13;
}
}
BOOL WINAPI DllMain(HINSTANCE module,DWORD reason,void*){
    if(reason==DLL_PROCESS_ATTACH){own=module;DisableThreadLibraryCalls(module);HANDLE thread=CreateThread(nullptr,0,&run,nullptr,0,nullptr);if(thread)CloseHandle(thread);}return TRUE;
}
#ifdef HALFLIGHT_DAMAGE_FIXTURE
float fixture_health(const void* module){float result=0;std::memcpy(&result,static_cast<const unsigned char*>(module)+0x28,4);return result;}
unsigned fixture_forwarded=0,fixture_copied=0,fixture_destroyed=0;
void fixture_original(void*,void*,void*){++fixture_forwarded;}
const void* fixture_data(const void* message){return static_cast<const unsigned char*>(message)+8;}
void* fixture_copy(void* output,const void* input){
    ++fixture_copied;std::memcpy(output,input,0xe0);const std::uintptr_t owned=0x987654,pool=0xabc123;
    std::memcpy(static_cast<unsigned char*>(output)+0x70,&owned,8);std::memcpy(static_cast<unsigned char*>(output)+0x78,&pool,8);return output;
}
void fixture_destroy(void*){++fixture_destroyed;}
const void* fixture_read_entity(const void*){return reinterpret_cast<const void*>(seed_attacker);}
unsigned fixture_assigned=0;
void* fixture_assign_entity(void* output,const void* entity){
    if(output==seed && entity==reinterpret_cast<const void*>(seed_attacker))++fixture_assigned;
    return output;
}
int main(){
    bool bank_poses[max_banks]{};
    if(std::any_of(bank_poses,bank_poses+max_banks,[](bool valid){return valid;}))return 51;
    for(unsigned i=0;i<max_banks;++i){
        bank_poses[i]=true;
        if(!std::any_of(bank_poses,bank_poses+max_banks,[](bool valid){return valid;}))return 52;
        bank_poses[i]=false;
    }
    unsigned char context_before[0xe0],context_after[0xe0];
    std::memset(context_before,0x5a,sizeof(context_before));
    for(unsigned category:{1u,18u,68u,72u}){
    std::memcpy(context_after,context_before,sizeof(context_after));prepare_melee_damage(context_after,category);
    for(unsigned i=0;i<sizeof(context_after);++i){
        unsigned char native_profile[16]{};const float profile[4]={category==1?.7f:0.f,0.f,category==1?.5f:0.f,category==1?.5f:0.f};
        std::memcpy(native_profile,profile,sizeof(profile));
        const auto expected=(i>=0x20 && i<0x24)?0:(i==0xd0?category:(i>=0x5c && i<0x6c?native_profile[i-0x5c]:context_before[i]));
        if(context_after[i]!=expected)return 49;
    }
    for(unsigned source:{0u,1u,2u,13u})for(unsigned destination:{1u,2u}){
        unsigned char row[0x110]{},original[0x110]{};
        const float native_terms[3]={19.f,20.f,21.f},armour[3]={80.f,80.f,80.f};
        row[source*16]=3;std::memcpy(row+source*16+4,native_terms,12);std::memcpy(row+0xb4,armour,12);
        std::memcpy(original,row,sizeof(row));
        if(!route_melee_factor(row,2,source,destination) || row[destination*16]!=3)return 57;
        float terms[3]{};std::memcpy(terms,row+destination*16+4,12);
        for(unsigned i=0;i<3;++i)if(terms[i]!=native_terms[i]*2)return 58;
        for(unsigned i=0;i<sizeof(row);++i)if(i/16!=source && i/16!=destination && row[i]!=original[i])return 59;
        if(source!=destination && std::memcmp(row+source*16,original+destination*16,16))return 60;
        std::memcpy(original,row,sizeof(row));
        if(route_melee_factor(row,-1,source,destination) || route_melee_factor(row,1,11,destination) ||
           route_melee_factor(row,1,source,16) || std::memcmp(row,original,sizeof(row)))return 61;
    }
    }
    WeaponContact long_contact{0x31574648,0,0,{0,1.5236f,0},{0,2.1305f,0},.095f,1};
    if(!valid_contact(long_contact))return 49;
    long_contact.b[1]=4.01f;if(valid_contact(long_contact))return 50;
    alignas(16) unsigned char pose_memory[128]{};const LONG stamp=2;
    std::memcpy(pose_memory,&stamp,4);view=pose_memory;cfg.pid=42;cfg.session=123;
    PosePacket supplied{0x324c4648,42,123,1,GetTickCount64(),{}},received{};
    std::memcpy(pose_memory+8,&supplied,80);if(!fresh_pose(received))return 38;
    supplied.magic=0x314c4648;std::memcpy(pose_memory+8,&supplied,80);if(!fresh_pose(received))return 39;
    supplied.magic=0x334c4648;std::memcpy(pose_memory+8,&supplied,80);if(!fresh_pose(received))return 40;
    supplied.magic=0x344c4648;std::memcpy(pose_memory+8,&supplied,80);if(!fresh_pose(received))return 45;
    supplied.magic=0x734c4648;std::memcpy(pose_memory+8,&supplied,80);if(fresh_pose(received))return 46;
    supplied.magic=0x324c4648;supplied.session=124;std::memcpy(pose_memory+8,&supplied,80);if(fresh_pose(received))return 41;
    alignas(16) unsigned char free_memory[128]{};std::memcpy(free_memory,&stamp,4);
    supplied.magic=0x334c4648;supplied.session=123;
    const float free_identity[12]={1,0,0,0,0,1,0,0,0,0,1,0};std::memcpy(supplied.matrix,free_identity,48);
    std::memcpy(pose_memory+8,&supplied,80);std::memcpy(free_memory+8,&supplied,80);
    dual=true;bank_count=54;type_count=27;free_view[0]=free_memory;
    if(!free_weapon_packet(0,received) || free_weapon_packet(0,received,true) || free_weapon_packet(1,received) || free_weapon_packet(27,received))return 51;
    supplied.matrix[3]=.2f;std::memcpy(pose_memory+8,&supplied,80);
    if(!free_weapon_packet(0,received,true) || received.matrix[3]!=0)return 52;
    supplied.sequence=2;std::memcpy(pose_memory+8,&supplied,80);if(free_weapon_packet(0,received))return 53;
    supplied.sequence=1;std::memcpy(pose_memory+8,&supplied,80);
    offhand_view=pose_memory;free_view[1]=free_memory;if(!free_weapon_packet(27,received,true))return 54;
    supplied.session=999;std::memcpy(free_memory+8,&supplied,80);if(free_weapon_packet(0,received))return 55;
    free_view[0]=free_view[1]=nullptr;offhand_view=nullptr;dual=false;bank_count=type_count=0;
    view=nullptr;cfg.pid=0;cfg.session=0;
    const char* grip_packet="Session=0123456789abcdef\nseq=1\nend_seq=1\nexpires_at=100\nenabled=1\nleft_enabled=0\nsocket=1,0,0,0,0,1,0,0.45,0,0,1,0\nright_socket=1,0,0,0,0,1,0,0,0,0,1,0\n";
    GuestGrip grip_test{};unsigned long long grip_sequence=0;
    if(!decode_grip(grip_packet,0x0123456789abcdef,100,grip_test,grip_sequence) || grip_sequence!=1 || !grip_test.enabled || grip_test.left_enabled)return 35;
    if(decode_grip(grip_packet,0x1123456789abcdef,100,grip_test,grip_sequence) || decode_grip(grip_packet,0x0123456789abcdef,102,grip_test,grip_sequence))return 36;
    char broken[512]{};std::snprintf(broken,sizeof(broken),"%sx=1\n",grip_packet);
    if(decode_grip(broken,0x0123456789abcdef,100,grip_test,grip_sequence))return 37;
    std::snprintf(broken,sizeof(broken),"%sright_enabled=0\n",grip_packet);
    if(!decode_grip(broken,0x0123456789abcdef,100,grip_test,grip_sequence) || grip_test.right_enabled)return 42;
    std::snprintf(broken,sizeof(broken),"%sright_enabled=2\n",grip_packet);
    if(decode_grip(broken,0x0123456789abcdef,100,grip_test,grip_sequence))return 43;
    std::snprintf(broken,sizeof(broken),"%sright_enabled=1\nright_enabled=0\n",grip_packet);
    if(decode_grip(broken,0x0123456789abcdef,100,grip_test,grip_sequence))return 44;
    std::snprintf(broken,sizeof(broken),"%sright_enabled=1\nweapon_index=1\n",grip_packet);
    if(!decode_grip(broken,0x0123456789abcdef,100,grip_test,grip_sequence) || grip_test.weapon_index!=1)return 47;
    std::snprintf(broken,sizeof(broken),"%sright_enabled=1\nweapon_index=64\n",grip_packet);
    if(decode_grip(broken,0x0123456789abcdef,100,grip_test,grip_sequence))return 48;
    auto player_arena=static_cast<unsigned char*>(VirtualAlloc(nullptr,65536,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE));if(!player_arena)return 29;
    const std::uint32_t player_header[3]={0x79534243,2,1},player_multiplier=1,player_shift=4;
    const std::uint16_t player_capacity=64;const std::uint64_t player_flags=1;
    std::memcpy(player_arena,player_header,12);std::memcpy(player_arena+0x20,&player_multiplier,4);std::memcpy(player_arena+0x24,&player_shift,4);
    std::memcpy(player_arena+0x2e,&player_capacity,2);std::memcpy(player_arena+0x30,&player_flags,8);
    seed_attacker=reinterpret_cast<std::uintptr_t>(player_arena+0x70);seed_attacker_handle=(std::uint64_t(1)<<34)|(std::uint64_t(2)<<28)|4;
    std::memcpy(player_arena+0x78,&seed_attacker_handle,8);read_entity=&fixture_read_entity;
    unsigned char receiver[64]{},entity[128]{},root[32]{},source[0xe0]{};
    const std::uint64_t receiver_handle=7,entity_handle=8,root_handle=9,borrowed_slot=0x123456;
    std::memcpy(source+0x70,&borrowed_slot,8);
    cfg.receiver=reinterpret_cast<std::uintptr_t>(receiver);cfg.entity=reinterpret_cast<std::uintptr_t>(entity);
    cfg.target_xform=reinterpret_cast<std::uintptr_t>(root);cfg.handle=receiver_handle;cfg.entity_handle=entity_handle;cfg.target_handle=root_handle;
    std::memcpy(receiver+8,&receiver_handle,8);std::memcpy(receiver+16,&cfg.entity,8);std::memcpy(entity+8,&entity_handle,8);
    std::memcpy(entity+0x58,&root_handle,8);std::memcpy(root+8,&root_handle,8);
    const std::uintptr_t message[3]={0x2efebe0,0x2eff340,reinterpret_cast<std::uintptr_t>(source)};
    original_hit=&fixture_original;get_data=&fixture_data;copy_damage=&fixture_copy;destroy_owner=&fixture_destroy;destroy_vector=&fixture_destroy;
    active.store(true);lease_live.store(true);hit_callback(receiver,nullptr,const_cast<std::uintptr_t*>(message));
    input_armed.store(true);
    hit_callback(receiver,nullptr,const_cast<std::uintptr_t*>(message));
    if(!seed_ready.load() || captured.load()!=1 || fixture_copied!=1 || fixture_forwarded!=1 || blocked_punches.load()!=1 || fixture_destroyed || in_flight.load())return 20;
    input_armed.store(false);hit_callback(receiver,nullptr,const_cast<std::uintptr_t*>(message));
    if(fixture_forwarded!=2 || blocked_punches.load()!=1)return 22;
    seed_ready.store(false);++cfg.handle;hit_callback(receiver,nullptr,const_cast<std::uintptr_t*>(message));
    if(fixture_forwarded!=3 || fixture_copied!=1 || captured.load()!=1)return 21;
    halflight_guard::LeaseGuard guard;Lease lease{0x31534648,42,123,1000};
    if(guard.update(nullptr,10,42,123) || !guard.update(&lease,100,42,123) || !guard.update(nullptr,999,42,123) || guard.update(nullptr,1000,42,123))return 23;
    lease.expiry=2000;if(!guard.update(&lease,1001,42,123))return 24;
    ++lease.session;if(guard.update(&lease,1002,42,123) || guard.update(nullptr,1003,42,123))return 25;
    auto arena=static_cast<unsigned char*>(VirtualAlloc(nullptr,65536,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE));if(!arena)return 26;
    const std::uint32_t magic=0x79534243,world=2,system=1,multiplier=1,shift=4;const std::uint16_t capacity=128;
    std::memcpy(arena,&magic,4);std::memcpy(arena+4,&world,4);std::memcpy(arena+8,&system,4);
    std::memcpy(arena+0x20,&multiplier,4);std::memcpy(arena+0x24,&shift,4);std::memcpy(arena+0x2e,&capacity,2);
    const std::uint64_t flags=(std::uint64_t(1)<<9)|(std::uint64_t(1)<<25)|(std::uint64_t(1)<<41);
    std::memcpy(arena+0x30,&flags,8);
    Binding binding{reinterpret_cast<std::uintptr_t>(arena+0x200),reinterpret_cast<std::uintptr_t>(arena+0x100),
        (std::uint64_t(1)<<34)|(std::uint64_t(2)<<28)|1,reinterpret_cast<std::uintptr_t>(arena+0x300),
        (std::uint64_t(1)<<34)|(std::uint64_t(2)<<28)|2,(std::uint64_t(1)<<34)|(std::uint64_t(2)<<28)|3};
    entity_table=0x123abc;skeleton_table=0x456def;const std::uintptr_t receiver_table=0x25695f8;
    std::memcpy(arena+0x100,&receiver_table,8);std::memcpy(arena+0x108,&binding.handle,8);std::memcpy(arena+0x110,&binding.entity,8);
    std::memcpy(arena+0x200,&entity_table,8);std::memcpy(arena+0x208,&binding.entity_handle,8);std::memcpy(arena+0x258,&binding.root_handle,8);
    std::memcpy(arena+0x300,&skeleton_table,8);std::memcpy(arena+0x308,&binding.root_handle,8);
    if(!binding_valid(binding))return 27;
    const auto inactive=flags&~(std::uint64_t(1)<<41);std::memcpy(arena+0x30,&inactive,8);
    if(binding_valid(binding))return 28;
    std::memcpy(arena+0x30,&flags,8);seed_ready.store(true);
    Binding second{reinterpret_cast<std::uintptr_t>(arena+0x500),reinterpret_cast<std::uintptr_t>(arena+0x400),
        (std::uint64_t(1)<<34)|(std::uint64_t(2)<<28)|5,reinterpret_cast<std::uintptr_t>(arena+0x600),
        (std::uint64_t(1)<<34)|(std::uint64_t(2)<<28)|6,(std::uint64_t(1)<<34)|(std::uint64_t(2)<<28)|7};
    const auto both_flags=flags|(std::uint64_t(1)<<57);const std::uint64_t upper_flags=(std::uint64_t(1)<<9)|(std::uint64_t(1)<<25);
    std::memcpy(arena+0x30,&both_flags,8);std::memcpy(arena+0x38,&upper_flags,8);
    std::memcpy(arena+0x400,&receiver_table,8);std::memcpy(arena+0x408,&second.handle,8);std::memcpy(arena+0x410,&second.entity,8);
    std::memcpy(arena+0x500,&entity_table,8);std::memcpy(arena+0x508,&second.entity_handle,8);std::memcpy(arena+0x558,&second.root_handle,8);
    std::memcpy(arena+0x600,&skeleton_table,8);std::memcpy(arena+0x608,&second.root_handle,8);
    TargetPacket packet{};packet.sequence=1;packet.expiry=2000;packet.count=2;packet.targets[0]=binding;packet.targets[1]=second;
    accept_targets(packet,1000);if(target_count.load()!=2 || !seed_owner_valid())return 30;
    packet.sequence=2;packet.count=1;packet.targets[0]=second;accept_targets(packet,1100);
    if(target_count.load()!=1 || !seed_ready.load() || !seed_owner_valid() || fixture_destroyed)return 31;
    packet.sequence=3;packet.count=0;accept_targets(packet,1200);if(target_count.load() || !seed_owner_valid())return 32;
    packet.sequence=4;packet.count=1;packet.expiry=1199;accept_targets(packet,1200);if(target_count.load())return 33;
    // The same health guard used immediately before each real dispatch.
    Binding health_binding=binding;
    health_binding.handle=(binding.handle&~0x0fffffffull)|0x10;
    health_binding.entity_handle=(binding.entity_handle&~0x0fffffffull)|0x20;
    health_binding.root_handle=(binding.root_handle&~0x0fffffffull)|0x30;
    std::memcpy(arena+0x108,&health_binding.handle,8);std::memcpy(arena+0x208,&health_binding.entity_handle,8);
    std::memcpy(arena+0x258,&health_binding.root_handle,8);std::memcpy(arena+0x308,&health_binding.root_handle,8);
    alignas(16) unsigned char human[0x700]{},registry[0x80]{},health_module[0x80]{},tuple[0x40]{};
    const auto hp=reinterpret_cast<std::uintptr_t>(human),rp=reinterpret_cast<std::uintptr_t>(registry),mp=reinterpret_cast<std::uintptr_t>(health_module),tp=reinterpret_cast<std::uintptr_t>(tuple);
    const std::uintptr_t observable_table=0x2abc1e0,human_table=0x2ca1980,health_table=0x2a9ec30,owner=hp+0x80;
    const std::uint64_t component_handle=(binding.handle&~0x0fffffffull)|0x70;
    const auto span=(std::uint64_t(2)<<56)|reinterpret_cast<std::uintptr_t>(&component_handle);
    std::memcpy(arena+0x278,&span,8);std::memcpy(arena+0x700,&observable_table,8);std::memcpy(arena+0x708,&component_handle,8);
    std::memcpy(arena+0x710,&health_binding.entity,8);std::memcpy(arena+0x778,&hp,8);
    std::memcpy(human,&human_table,8);std::memcpy(human+0x608,&rp,8);std::memcpy(registry+0x70,&mp,8);
    std::memcpy(health_module,&health_table,8);std::memcpy(health_module+8,&owner,8);
    const auto tuple_slot=reinterpret_cast<std::uintptr_t>(&tp);std::memcpy(health_module+0x18,&tuple_slot,8);
    const auto occupied_health=upper_flags|(std::uint64_t(1)<<41);std::memcpy(arena+0x38,&occupied_health,8);
    native_health.get=&fixture_health;TargetState health_target{};health_target.binding=health_binding;
    float life=30;std::memcpy(health_module+0x28,&life,4);
    if(!living_target(health_target,2000) || health_target.health!=30)return 35;
    health_target.last_dispatch=2000;life=20;std::memcpy(health_module+0x28,&life,4);
    if(!living_target(health_target,2001) || measured_health_loss.load()!=10)return 36;
    life=0;std::memcpy(health_module+0x28,&life,4);
    if(living_target(health_target,2002) || !dead_target_frames.load())return 37;
    const std::uintptr_t wrong_owner=0;std::memcpy(health_module+8,&wrong_owner,8);
    if(living_target(health_target,2003) || !unknown_health_frames.load())return 38;
    seed_ready.store(false);target_count.store(0);cfg.receiver=cfg.entity=cfg.target_xform=0;
    const auto copies_before=fixture_copied;
    hit_callback(arena+0x100,nullptr,const_cast<std::uintptr_t*>(message));
    if(!seed_ready.load() || fixture_copied!=copies_before+1)return 56;
    seed_ready.store(false);cfg.seed_source=reinterpret_cast<std::uintptr_t>(source);
    assign_entity=&fixture_assign_entity;
    unsigned char old_attacker[16]{};std::memcpy(old_attacker,source,16);
    import_pending_seed(false);if(seed_ready.load() || !cfg.seed_source || fixture_assigned)return 57;
    import_pending_seed(true);if(!seed_ready.load() || cfg.seed_source || imported_seeds.load()!=1 || target_count.load() ||
       fixture_assigned!=1 || std::memcmp(old_attacker,source,16))return 58;
    import_pending_seed(true);if(fixture_copied!=copies_before+2)return 59;
    const auto replaced_handle=seed_attacker_handle+1;std::memcpy(player_arena+0x78,&replaced_handle,8);if(seed_owner_valid())return 34;
    VirtualFree(arena,0,MEM_RELEASE);VirtualFree(player_arena,0,MEM_RELEASE);
    puts("damage_fixture_passed: owned seed, punch filtering, multiple victims, replacement retains attacker seed, stale identities, native health loss, corpse and unknown-health refusal");return 0;
}
#endif
#ifdef HALFLIGHT_STARTUP_FIXTURE
DWORD WINAPI fixture_startup(void*){
    const unsigned char wrong_hash[32]{};
    if(hash_matches(own,wrong_hash))return 90;
    // Same startup path, but this fixture is not a game and has no config.
    // It must refuse before any callback installation.
    return run(nullptr);
}
int main(){
    own=GetModuleHandleW(nullptr);
    const HANDLE worker=CreateThread(nullptr,1024*1024,&fixture_startup,nullptr,STACK_SIZE_PARAM_IS_A_RESERVATION,nullptr);
    if(!worker)return 91;
    const auto waited=WaitForSingleObject(worker,15000);DWORD code=0;
    const bool returned=waited==WAIT_OBJECT_0 && GetExitCodeThread(worker,&code);
    CloseHandle(worker);
    if(!returned || code!=3)return 92;
    wchar_t path[1024]{};GetModuleFileNameW(own,path,1024);auto slash=wcsrchr(path,L'\\');if(!slash)return 93;
    swprintf(slash+1,1024-(slash+1-path),L"native-axe-damage-%lu.log",GetCurrentProcessId());DeleteFileW(path);
    puts("startup_fixture_passed: hash validation and real startup refusal on a 1MB reserved worker stack, no game hooks");return 0;
}
#endif
