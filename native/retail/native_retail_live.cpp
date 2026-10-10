// Original bounded live-pose adapter, reusing the verified native movement path. No instruction patches or Frida.
#include "native_module_hash.h"
#include "native_weapon_live.h"
#include "weapon_slots.h"
#include "lease_guard.h"
using namespace halflight_slots;
#include <atomic>
#include <cstdio>
#include <cwchar>
#include <cstring>
#include <chrono>
using namespace halflight;
namespace {
using Update=void(*)(void*);
using SetMatrix=void(*)(void*,const Matrix34&);
HMODULE own=nullptr;
std::uintptr_t engine=0,game=0;
void** slot=nullptr;Update original_update=nullptr;
std::atomic<bool> active{false},done{false};
std::atomic<unsigned> calls{0},writes{0},in_flight{0},phase_refusals{0};
std::atomic<unsigned> last_mode{~0u},last_lane{~0u};
std::atomic_flag writing=ATOMIC_FLAG_INIT;
NativeWeaponLive replay;Matrix34 original_pose{};
std::atomic_flag packet_lock=ATOMIC_FLAG_INIT;
LivePose latest{};bool have_pose=false;
std::atomic<unsigned> packets{0};
double pose_clock(){return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();}
bool armed=false;
bool continuous=false;
bool follow_player=false;
std::atomic<bool> lease_alive{true};
#pragma pack(push,1)
struct Config {std::uint32_t magic,pid;std::uint64_t mesh,xform,handle,xform_handle,receiver,nonce;};
#pragma pack(pop)
Config config{};
struct WeaponBank {Config config;float original[12];};
static_assert(sizeof(WeaponBank)==104);
WeaponBank banks[max_banks]{};bool dual=false;unsigned current_weapon=0,bank_count=0,type_count=0;
std::uint64_t stream_sequence[2]{};

LivePose bank_latest[max_banks]{};bool bank_have[max_banks]{},bank_present[max_banks]{},bank_armed[max_banks]{};
bool bank_visibility_saved[max_banks]{},bank_original_active[max_banks]{};
std::atomic<BankMask> visibility_changed{0};
bool all_restored(){for(unsigned i=0;i<bank_count;++i)if(bank_armed[i])return false;return visibility_changed.load()==0;}
NativeWeaponLive bank_replay[max_banks];std::atomic<BankMask> drawn_mask{0};
std::atomic<unsigned> drawn_weapon{0};
void select_weapon(unsigned index){
    const auto& bank=banks[index];config.mesh=bank.config.mesh;config.xform=bank.config.xform;
    config.handle=bank.config.handle;config.xform_handle=bank.config.xform_handle;memcpy(original_pose.values.data(),bank.original,48);
    current_weapon=index;
}
struct CameraConfig {std::uint64_t object,table,transform,transform_table;};
CameraConfig camera_config{};
HANDLE pose_mapping=nullptr;const unsigned char* pose_view=nullptr;
HANDLE offhand_mapping=nullptr;const unsigned char* offhand_view=nullptr;
halflight_guard::LeaseGuard lease_guard;
bool poll_lease(const wchar_t* path) {
    HANDLE file=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
    halflight_guard::Lease value{};bool readable=false,malformed=false;
    if(file!=INVALID_HANDLE_VALUE){
        DWORD got=0;readable=ReadFile(file,&value,sizeof(value),&got,nullptr)!=0;
        malformed=readable && (got!=sizeof(value) || GetFileSize(file,nullptr)!=sizeof(value));CloseHandle(file);
    }
    if(malformed)value={};
    return lease_guard.update(readable?&value:nullptr,GetTickCount64(),config.pid,config.nonce);
}
#pragma pack(push,1)
struct Packet {std::uint32_t magic,pid;std::uint64_t nonce,sequence,published_ms;float matrix[12];};
#pragma pack(pop)
static_assert(sizeof(Packet)==80);
bool poll_packet(const wchar_t* path,bool offhand=false) {
    Packet p{};bool ok=false;
    if(continuous) {
        auto& mapping=offhand?offhand_mapping:pose_mapping;auto& view=offhand?offhand_view:pose_view;
        if(!mapping) {
            wchar_t name[128]{};swprintf(name,128,L"Local\\HalfLightAxe-%lu-%016llx%ls",config.pid,static_cast<unsigned long long>(config.nonce),offhand?L"-offhand":L"");
            mapping=OpenFileMappingW(FILE_MAP_READ,FALSE,name);
            if(mapping)view=static_cast<const unsigned char*>(MapViewOfFile(mapping,FILE_MAP_READ,0,0,128));
        }
        if(!view)return false;
        const auto stamp=*reinterpret_cast<const volatile LONG*>(view);
        if(!stamp || (stamp&1))return false;
        MemoryBarrier();memcpy(&p,view+8,sizeof(p));MemoryBarrier();
        ok=stamp==*reinterpret_cast<const volatile LONG*>(view);
    } else {
        HANDLE file=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
        if(file==INVALID_HANDLE_VALUE)return false;
        DWORD got=0;ok=ReadFile(file,&p,sizeof(p),&got,nullptr) && got==sizeof(p) && GetFileSize(file,nullptr)==sizeof(p);CloseHandle(file);
    }
    const auto now=GetTickCount64();
    unsigned type=0;bool present=false;
    const bool tagged=dual?pose_tag(p.magic,type_count,type,present):p.magic==(follow_player?0x324c4648u:0x314c4648u);
    if(!ok || !tagged || p.pid!=config.pid || p.nonce!=config.nonce || !p.sequence || p.published_ms>now || now-p.published_ms>250)return false;
    Matrix34 matrix{};memcpy(matrix.values.data(),p.matrix,48);
    for(float v:matrix.values)if(!std::isfinite(v))return false;
    if(packet_lock.test_and_set(std::memory_order_acquire))return false;
    if(dual){
        const unsigned group=offhand?1:0,offset=group*type_count,index=offset+type;
        if(p.sequence>stream_sequence[group]){
            stream_sequence[group]=p.sequence;
            for(unsigned i=offset;i<offset+type_count;++i)bank_present[i]=false;
            bank_latest[index]={p.sequence,pose_clock()-(now-p.published_ms)/1000.0,matrix};bank_have[index]=true;
            bank_present[index]=present;packets.fetch_add(1);
        }
        packet_lock.clear(std::memory_order_release);return true;
    }
    if(!have_pose || p.sequence>latest.sequence) {
        // Keep the packet's issued age, but interpolate on a high-resolution
        // monotonic clock instead of coarse Windows uptime milliseconds.
        latest={p.sequence,pose_clock()-(now-p.published_ms)/1000.0,matrix};have_pose=true;packets.fetch_add(1);
    }
    packet_lock.clear(std::memory_order_release);return true;
}
template<class T> bool read(std::uintptr_t address,T& value) {
    SIZE_T copied=0;
    return address>=0x10000 && address<0x800000000000 &&
        ReadProcessMemory(GetCurrentProcess(),reinterpret_cast<void*>(address),&value,sizeof(value),&copied) && copied==sizeof(value);
}
bool object_valid() {
    std::uint64_t table=0,handle=0,xform=0;
    if(!read(config.mesh,table) || table!=engine+0x18ca5d8 ||
       !read(config.mesh+8,handle) || handle!=config.handle ||
       !read(config.mesh+0x98,xform) || xform!=config.xform ||
       !read(config.xform,table) || table!=engine+0x181ba08 ||
       !read(config.xform+8,handle) || handle!=config.xform_handle)return false;
    std::uint64_t setter=0;
    if(!read(table+0x420,setter) || setter!=engine+0x446a80)return false;
    const auto chunk=config.mesh&~std::uint64_t(0x3fff);
    std::uint32_t magic=0,world=0,system=0,multiplier=0,shift=0;
    std::uint16_t capacity=0;
    if(!read(chunk,magic) || magic!=0x79534243 || !read(chunk+4,world) || !read(chunk+8,system) ||
       world!=((config.handle>>28)&63) || system!=((config.handle>>34)&1023) ||
       !read(chunk+0x20,multiplier) || !read(chunk+0x24,shift) || !read(chunk+0x2e,capacity))return false;
    const auto index=((config.mesh-chunk-0x70)*multiplier)>>(shift&63);
    std::uint64_t bitmap=0;
    return index<capacity && 0x30+(index/64)*8+8<=0x70 &&
        read(chunk+0x30+(index/64)*8,bitmap) && (bitmap&(std::uint64_t(1)<<(index%64)));
}
bool writable_phase() {
    std::uintptr_t owner=0,manager=0,lane_owner=0,backup=0;
    DWORD mode_key=0,lane_key=0;
    if(!read(engine+0x180c6f0,owner) || !read(owner,manager) || !read(manager+8,mode_key) ||
       !read(engine+0x180c6f8,lane_owner) || !read(lane_owner,lane_key) ||
       mode_key>=1088 || lane_key>=1088)return false;
    const auto mode=reinterpret_cast<std::uintptr_t>(TlsGetValue(mode_key));
    const auto lane=reinterpret_cast<std::uintptr_t>(TlsGetValue(lane_key));
    last_mode.store(static_cast<unsigned>(mode));last_lane.store(static_cast<unsigned>(lane));
    if(mode>=2 || !lane || lane>128 || !read(manager+0x10+(lane-1)*8,backup))return false;
    std::uint64_t first=0;return read(backup,first);
}
bool matrices_close(const Matrix34& a,const Matrix34& b) {
    for(unsigned i=0;i<12;++i)if(std::abs(a.values[i]-b.values[i])>0.0001f)return false;
    return true;
}
// Native CComponent::SetSelfActive changes only the owned mesh renderer, not
// its hierarchy, floor collision or pose. Keep the exact prior editor state.
bool bank_visibility(unsigned index,bool shown,bool restore){
    unsigned char current=0;
    if(!read(config.mesh+0x24,current) || current>1)return false;
    if(!bank_visibility_saved[index]){
        if(restore)return true;
        bank_original_active[index]=current!=0;bank_visibility_saved[index]=true;
    }
    const bool wanted=restore?bank_original_active[index]:shown;
    if((current!=0)!=wanted){
        using Setter=bool(*)(void*,const bool&);
        if(!reinterpret_cast<Setter>(engine+0x4a3ad0)(reinterpret_cast<void*>(config.mesh),wanted) ||
           !read(config.mesh+0x24,current) || (current!=0)!=wanted)return false;
    }
    if(wanted==bank_original_active[index])visibility_changed.fetch_and(~bank_bit(index));
    else visibility_changed.fetch_or(bank_bit(index));
    return true;
}
bool camera_pose(Matrix34& matrix) {
    std::uint64_t table=0,transform=0;
    if(!read(camera_config.object,table) || table!=camera_config.table ||
       !read(camera_config.object+0x38,transform) || transform!=camera_config.transform ||
       !read(transform,table) || table!=camera_config.transform_table || !read(transform+0x40,matrix))return false;
    for(float v:matrix.values)if(!std::isfinite(v) || std::abs(v)>100000)return false;
    for(unsigned axis=0;axis<3;++axis) {
        double length=0;for(unsigned row=0;row<3;++row)length+=matrix.values[row*4+axis]*matrix.values[row*4+axis];
        if(std::abs(length-1)>.05)return false;
    }
    return true;
}
struct NativeSink:EngineSink {
    bool apply(const CallbackContext& context,const Matrix34& matrix) override {
        if(context.verified_update_owner!=config.receiver || !object_valid() || !writable_phase())return false;
        if(follow_player && !matrices_close(matrix,original_pose)) {
            Matrix34 camera{};if(!camera_pose(camera))return false;
            double distance=0;for(unsigned row=0;row<3;++row){const double d=matrix.values[row*4+3]-camera.values[row*4+3];distance+=d*d;}
            if(distance>9)return false;
        }
        auto setter=reinterpret_cast<SetMatrix>(engine+0x446a80);
        setter(reinterpret_cast<void*>(config.xform),matrix);
        writes.fetch_add(1);
        Matrix34 actual{};return read(config.xform+0x80,actual) && matrices_close(actual,matrix);
    }
} sink;
void update_weapons(double now,const Matrix34& camera,bool camera_ok){
    LivePose poses[max_banks]{};bool available[max_banks]{},present[max_banks]{};
    if(packet_lock.test_and_set(std::memory_order_acquire))return;
    for(unsigned i=0;i<bank_count;++i){poses[i]=bank_latest[i];available[i]=bank_have[i];present[i]=bank_present[i];}
    packet_lock.clear(std::memory_order_release);
    BankMask mask=0;
    for(unsigned i=0;i<bank_count;++i){
        if(!present[i] && !bank_armed[i])continue;
        select_weapon(i);
        if(!object_valid()){done.store(true);continue;}
        const CallbackContext context{GetCurrentProcessId(),config.handle,GetCurrentThreadId(),true,config.receiver};
        const bool fresh=available[i] && poses[i].published<=now && now-poses[i].published<=.25;
        if(!bank_armed[i] && present[i] && fresh && lease_alive.load() && camera_ok){
            Matrix34 current{},render{};
            if(!read(config.xform+0x80,current) || !read(config.xform+0xe0,render) || !matrices_close(current,original_pose) ||
               !matrices_close(render,original_pose) || !bank_replay[i].arm(context,original_pose,now,0)){done.store(true);continue;}
            bank_armed[i]=true;
        }
        if(bank_armed[i]){
            bank_replay[i].update(context,available[i]?&poses[i]:nullptr,now,sink,lease_alive.load() && camera_ok && present[i],&camera,true);
            if(bank_replay[i].state()==ReplayState::invalidated)done.store(true);
            else if(bank_replay[i].state()==ReplayState::finished)bank_armed[i]=false;
            else if(fresh && present[i])mask|=bank_bit(i);
        }
    }
    const BankMask previous_mask=drawn_mask.load();
    const bool restoring=!lease_alive.load() || !camera_ok || done.load();
    for(unsigned i=0;i<bank_count;++i){
        // Untouched hidden banks need no engine reads on every rendered frame.
        if(bank_visibility_saved[i] && !restoring && !((mask^previous_mask)&bank_bit(i)))continue;
        if(bank_visibility_saved[i] && restoring && !(visibility_changed.load()&bank_bit(i)))continue;
        select_weapon(i);
        if(object_valid() && !bank_visibility(i,(mask&bank_bit(i))!=0,restoring))done.store(true);
    }
    drawn_mask.store(mask);for(unsigned i=0;i<bank_count;++i)if(mask&(bank_bit(i))){drawn_weapon.store(i);break;}
    if((!lease_alive.load() || !camera_ok) && all_restored())done.store(true);
}
void callback(void* self) {
    in_flight.fetch_add(1);
    original_update(self);
    calls.fetch_add(1);
    if(active.load() && !done.load() && reinterpret_cast<std::uintptr_t>(self)==config.receiver &&
       !writing.test_and_set(std::memory_order_acquire)) {
        std::uintptr_t table=0;
        const bool valid=read(config.receiver,table) && table==game+0x241eba8 && object_valid();
        if(!valid)done.store(true);
        else if(!writable_phase())phase_refusals.fetch_add(1);
        else {
            const CallbackContext context{GetCurrentProcessId(),config.handle,GetCurrentThreadId(),true,config.receiver};
            const double now=pose_clock();
            Matrix34 camera{};const bool camera_ok=!follow_player || camera_pose(camera);
            if(dual){update_weapons(now,camera,camera_ok);writing.clear(std::memory_order_release);in_flight.fetch_sub(1);return;}
            LivePose pose{};bool available=false;
            if(!packet_lock.test_and_set(std::memory_order_acquire)) {
                pose=latest;available=have_pose;packet_lock.clear(std::memory_order_release);
            } else {writing.clear(std::memory_order_release);in_flight.fetch_sub(1);return;}
            const bool fresh=available && pose.published<=now && now-pose.published<=.25;
            if(!armed) {
                Matrix34 current{},render{};
                if(continuous && !lease_alive.load())done.store(true);
                else if(continuous && !fresh) {writing.clear(std::memory_order_release);in_flight.fetch_sub(1);return;}
                else if(!read(config.xform+0x80,current) || !read(config.xform+0xe0,render) ||
                   !matrices_close(current,original_pose) || !matrices_close(render,original_pose) ||
                   !replay.arm(context,original_pose,now,continuous?0:30))done.store(true);
                else armed=true;
            }
            if(armed) {
                replay.update(context,available?&pose:nullptr,now,sink,lease_alive.load() && camera_ok,follow_player?&camera:nullptr,follow_player);
                if(replay.state()==ReplayState::playing)drawn_weapon.store(current_weapon);
                if(replay.state()==ReplayState::invalidated)done.store(true);
                else if(replay.state()==ReplayState::finished) {
                    if(continuous && lease_alive.load() && camera_ok)armed=false;
                    else done.store(true);
                }
            }
        }
        writing.clear(std::memory_order_release);
    }
    in_flight.fetch_sub(1);
}
bool replace(void* desired,void* expected) {
    DWORD old=0,temp=0;if(!VirtualProtect(slot,8,PAGE_READWRITE,&old))return false;
    void* found=InterlockedCompareExchangePointer(reinterpret_cast<void* volatile*>(slot),desired,expected);
    const bool protected_again=VirtualProtect(slot,8,old,&temp)!=0;
    return found==expected && protected_again;
}
DWORD WINAPI run(void*) {
    static wchar_t path[32768]{};if(!GetModuleFileNameW(own,path,32768))return 1;
    wchar_t* slash=wcsrchr(path,L'\\');if(!slash)return 2;*slash=0;
    static wchar_t input_path[32768]{},log_path[32768]{},packet_path[32768]{},lease_path[32768]{},status_path[32768]{};
    swprintf(input_path,32768,L"%ls\\native-axe-live-%lu.config",path,GetCurrentProcessId());
    swprintf(log_path,32768,L"%ls\\native-axe-live-%lu.log",path,GetCurrentProcessId());
    swprintf(packet_path,32768,L"%ls\\native-axe-live-%lu.packet",path,GetCurrentProcessId());
    swprintf(lease_path,32768,L"%ls\\native-axe-session-%lu.lease",path,GetCurrentProcessId());
    swprintf(status_path,32768,L"%ls\\native-axe-session-%lu.status",path,GetCurrentProcessId());
    FILE* log=_wfopen(log_path,L"wb");if(!log)return 3;
    HMODULE pinned=nullptr;
    if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_PIN|GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS,
                          reinterpret_cast<LPCWSTR>(&callback),&pinned)){fputs("status,pin_failed\n",log);fclose(log);return 4;}
    static wchar_t image[32768]{};GetModuleFileNameW(nullptr,image,32768);const auto name=wcsrchr(image,L'\\');
    if(!name || _wcsicmp(name+1,L"DyingLightGame_x64_rwdi.exe")){fputs("status,wrong_process\n",log);fclose(log);return 5;}
    const auto game_module=GetModuleHandleW(L"gamedll_ph_x64_rwdi.dll"),engine_module=GetModuleHandleW(L"engine_x64_rwdi.dll");
    const unsigned char game_hash[32]={0xb4,0x17,0x21,0x3b,0x3b,0x1e,0x70,0xb9,0xbb,0x58,0x9b,0x88,0xd3,0x88,0xbb,0x99,0xdd,0x21,0x3b,0x90,0x82,0xd4,0x4e,0xf3,0x8f,0x40,0x21,0x14,0x6f,0x6e,0xe6,0xc4};
    const unsigned char engine_hash[32]={0xa0,0x65,0x19,0xee,0x1f,0xd7,0x9d,0xe1,0xd6,0x65,0x21,0x5f,0x38,0xe6,0xb8,0x9f,0x2b,0x07,0x4b,0xf9,0x74,0x59,0x12,0xc6,0x4a,0x6f,0x06,0x84,0x61,0x7a,0xdb,0x63};
    if(!game_module || !engine_module || !hash_matches(game_module,game_hash) || !hash_matches(engine_module,engine_hash)) {
        fputs("status,module_mismatch\n",log);fclose(log);return 6;
    }
    game=reinterpret_cast<std::uintptr_t>(game_module);engine=reinterpret_cast<std::uintptr_t>(engine_module);
    FILE* input=_wfopen(input_path,L"rb");if(!input){fputs("status,input_missing\n",log);fclose(log);return 7;}
    bool ok=fread(&config,sizeof(config),1,input)==1 && (config.magic==0x31434648 || config.magic==0x32434648 || config.magic==0x33434648) && config.pid==GetCurrentProcessId() && config.nonce &&
        fread(original_pose.values.data(),48,1,input)==1;
    follow_player=config.magic==0x33434648;
    if(follow_player)ok=ok && fread(&camera_config,sizeof(camera_config),1,input)==1;
    ok=ok && fgetc(input)==EOF;fclose(input);
    if(!ok || !object_valid()){fputs("status,input_or_object_invalid\n",log);fclose(log);return 8;}
    static wchar_t dual_path[32768]{};swprintf(dual_path,32768,L"%ls\\native-weapons-live-%lu.config",path,config.pid);
    FILE* dual_file=_wfopen(dual_path,L"rb");
    if(dual_file){
        fseek(dual_file,0,SEEK_END);const long bytes=ftell(dual_file);rewind(dual_file);
        bank_count=bytes>0?unsigned(bytes/sizeof(WeaponBank)):0;type_count=bank_count/2;
        ok=follow_player && bank_count>=2 && bank_count<=max_banks && !(bank_count&1) && bytes==long(bank_count*sizeof(WeaponBank)) && fread(banks,sizeof(WeaponBank),bank_count,dual_file)==bank_count && fgetc(dual_file)==EOF;fclose(dual_file);
        const auto initial=config;
        for(unsigned i=0;i<bank_count && ok;++i){
            const auto& c=banks[i].config;
            ok=c.magic==initial.magic && c.pid==initial.pid && c.nonce==initial.nonce && c.receiver==initial.receiver;
            if(ok){select_weapon(i);ok=object_valid();}
            for(float v:banks[i].original)ok=ok && std::isfinite(v);
            for(unsigned j=0;j<i;++j)ok=ok && c.xform!=banks[j].config.xform && c.mesh!=banks[j].config.mesh;
        }
        if(!ok){fputs("status,weapon_banks_refused\n",log);fclose(log);return 8;}
        dual=true;unsigned initial_index=0;for(unsigned i=0;i<bank_count;++i)if(initial.mesh==banks[i].config.mesh)initial_index=i;select_weapon(initial_index);drawn_weapon.store(current_weapon);
    }
    continuous=config.magic!=0x31434648;
    Matrix34 first_camera{};
    if(follow_player && !camera_pose(first_camera)){fputs("status,camera_identity_invalid\n",log);fclose(log);return 8;}
    if(continuous && !poll_lease(lease_path)){fputs("status,session_lease_missing\n",log);fclose(log);return 8;}
    slot=reinterpret_cast<void**>(game+0x241eba8+0x3b0);original_update=reinterpret_cast<Update>(*slot);
    if(reinterpret_cast<std::uintptr_t>(original_update)!=game+0x1cc85c8) {
        fputs("status,callback_mismatch\n",log);fclose(log);return 9;
    }
    active.store(true);
    if(!replace(reinterpret_cast<void*>(&callback),reinterpret_cast<void*>(original_update))) {
        active.store(false);replace(reinterpret_cast<void*>(original_update),reinterpret_cast<void*>(&callback));
        fputs("status,install_failed\n",log);fclose(log);return 10;
    }
    const auto began=GetTickCount64();
    const auto deadline=continuous?~ULONGLONG(0):began+32000;
    ULONGLONG stop_at=0,last_status=0;
    while(!done.load() && GetTickCount64()<deadline) {
        const auto now=GetTickCount64();
        if(continuous && !poll_lease(lease_path) && !stop_at){lease_alive.store(false);stop_at=now+2000;}
        if(stop_at && now>=stop_at)break;
        poll_packet(packet_path);
        if(dual)poll_packet(packet_path,true);
        if(continuous && now-last_status>=1000) {
            FILE* status=_wfopen(status_path,L"wb");
            if(status){fprintf(status,"session,%llx\npose_calls,%u\npackets,%u\nelapsed_ms,%llu\nlease_alive,%d\nweapon_mask,%llu\n",static_cast<unsigned long long>(config.nonce),writes.load(),packets.load(),static_cast<unsigned long long>(now-began),lease_alive.load()?1:0,static_cast<unsigned long long>(drawn_mask.load()));fclose(status);}
            last_status=now;
        }
        Sleep(5);
    }
    active.store(false);
    if(continuous){
        // Ask chained arm/damage callbacks to restore before removing their
        // movement owner. No stale object is touched while this drains.
        static wchar_t rebind_path[32768]{};
        swprintf(rebind_path,32768,L"%ls\\native-axe-rebind-%lu.signal",path,GetCurrentProcessId());
        HANDLE signal=CreateFileW(rebind_path,GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);
        if(signal!=INVALID_HANDLE_VALUE)CloseHandle(signal);
        const auto chain_deadline=GetTickCount64()+2500;
        while(*slot!=reinterpret_cast<void*>(&callback) && GetTickCount64()<chain_deadline)Sleep(5);
    }
    if(pose_view)UnmapViewOfFile(pose_view);
    if(pose_mapping)CloseHandle(pose_mapping);
    if(offhand_view)UnmapViewOfFile(offhand_view);
    if(offhand_mapping)CloseHandle(offhand_mapping);
    const bool restored=replace(reinterpret_cast<void*>(original_update),reinterpret_cast<void*>(&callback));
    const auto drain=GetTickCount64()+100;
    while(in_flight.load() && GetTickCount64()<drain)Sleep(1);
    const bool drained=in_flight.load()==0;
    const bool pose_restored=drained && (dual?(all_restored()):replay.state()==ReplayState::finished);
    fprintf(log,"status,%s\ncallback_restored,%d\npose_restored,%d\ncalls,%u\npose_calls,%u\npackets,%u\nelapsed_ms,%llu\nphase_refusals,%u\nlast_mode,%u\nlast_lane,%u\ncomplete,1\n",
            pose_restored && restored?"live_finished":"live_not_completed",restored?1:0,pose_restored?1:0,
            calls.load(),writes.load(),packets.load(),static_cast<unsigned long long>(GetTickCount64()-began),phase_refusals.load(),last_mode.load(),last_lane.load());
    fclose(log);return pose_restored && restored?0:11;
}
}
extern "C" __declspec(dllexport) unsigned HLF_WeaponIndex(){return drawn_weapon.load();}
extern "C" __declspec(dllexport) BankMask HLF_WeaponMask(){return drawn_mask.load();}
#ifdef HALFLIGHT_LIVE_VISIBILITY_FIXTURE
bool fixture_visibility_setter(void* mesh,const bool& value){reinterpret_cast<unsigned char*>(mesh)[0x24]=value?1:0;return true;}
int main(){
    (void)&run;
    bank_count=max_banks;for(unsigned i=0;i<bank_count;++i)bank_visibility_saved[i]=true;
    Matrix34 camera{};update_weapons(1,camera,true);
    if(done.load() || writes.load())return 6;
    bank_present[0]=true;update_weapons(1,camera,true);
    if(!done.load())return 7;
    done.store(false);bank_present[0]=false;bank_count=0;
    for(unsigned i=0;i<max_banks;++i)bank_visibility_saved[i]=false;
    unsigned char mesh[0x30]{};config.mesh=reinterpret_cast<std::uintptr_t>(mesh);
    engine=reinterpret_cast<std::uintptr_t>(&fixture_visibility_setter)-0x4fcb40;
    mesh[0x24]=1;
    if(!bank_visibility(0,false,false) || mesh[0x24] || visibility_changed.load()!=bank_bit(0))return 1;
    if(!bank_visibility(0,true,false) || mesh[0x24]!=1 || visibility_changed.load())return 2;
    if(!bank_visibility(0,false,false) || !bank_visibility(0,false,true) || mesh[0x24]!=1 || visibility_changed.load())return 3;
    mesh[0x24]=0;
    if(!bank_visibility(1,true,false) || mesh[0x24] || !bank_visibility(1,false,true) || mesh[0x24] || visibility_changed.load())return 4;
    mesh[0x24]=2;if(bank_visibility(2,false,false))return 5;
    puts("visibility_fixture_passed: selected renderer only, empty hand hidden, stop/camera loss restore exact state, originally inactive preserved, invalid state refused");return 0;
}
#else
BOOL WINAPI DllMain(HINSTANCE module,DWORD reason,void*) {
    if(reason==DLL_PROCESS_ATTACH) {
        own=module;DisableThreadLibraryCalls(module);
        HANDLE worker=CreateThread(nullptr,0,&run,nullptr,0,nullptr);if(worker)CloseHandle(worker);
    }
    return TRUE;
}
#endif
