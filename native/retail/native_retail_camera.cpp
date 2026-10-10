// Process-local raw mouse filter. MinHook: Tsuda Kageyu, BSD-2-Clause.
// The separate input companion still receives unmodified physical deltas.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wincrypt.h>
#include <atomic>
#include <cstdio>
#include <cwchar>
#include <cstring>
#include <ctime>
#include "MinHook.h"
#include "native_module_hash.hpp"
#include "lease_guard.h"
#include "input_lock_guard.h"
namespace {
using RawFn=UINT(WINAPI*)(HRAWINPUT,UINT,LPVOID,PUINT,UINT);
using BufferFn=UINT(WINAPI*)(PRAWINPUT,PUINT,UINT);
using KeyFn=SHORT(WINAPI*)(int);
using KeyboardFn=BOOL(WINAPI*)(PBYTE);
struct Config{unsigned magic,pid;unsigned long long session;unsigned char raw_prefix[32],buffer_prefix[32];};
static_assert(sizeof(Config)==80);
HMODULE own=nullptr;RawFn original_raw=nullptr;BufferFn original_buffer=nullptr;
std::atomic<bool> enabled{false};std::atomic<ULONGLONG> valid_until{0};
std::atomic<unsigned long long> calls{0},filtered{0},missed_reads{0};
KeyFn original_async=nullptr,original_key=nullptr;KeyboardFn original_keyboard=nullptr;
struct InputImport {void** slot=nullptr;void* original=nullptr;void* replacement=nullptr;};
InputImport imports[3]{};
bool forwarding(){DWORD pid=0;GetWindowThreadProcessId(GetForegroundWindow(),&pid);
    return enabled.load() && GetTickCount64()<valid_until.load() && pid==GetCurrentProcessId() && !(GetAsyncKeyState(VK_ESCAPE)&0x8000);}
bool locking(){return forwarding() && ((GetAsyncKeyState(VK_LBUTTON)|GetAsyncKeyState(VK_RBUTTON))&0x8000);}
SHORT filter_key(int key,SHORT state,bool active){return active && (key==VK_LBUTTON || key==VK_RBUTTON)?0:state;}
SHORT WINAPI async_hook(int key){return filter_key(key,original_async(key),forwarding());}
SHORT WINAPI key_hook(int key){return filter_key(key,original_key(key),forwarding());}
BOOL WINAPI keyboard_hook(PBYTE state){const auto ok=original_keyboard(state);if(ok && state && forwarding())state[VK_LBUTTON]=state[VK_RBUTTON]=0;return ok;}
bool replace_import(InputImport& entry,bool restore){
    DWORD old=0,temp=0;if(!VirtualProtect(entry.slot,sizeof(void*),PAGE_READWRITE,&old))return false;
    void* expected=restore?entry.replacement:entry.original;void* desired=restore?entry.original:entry.replacement;
    const auto found=InterlockedCompareExchangePointer(reinterpret_cast<void* volatile*>(entry.slot),desired,expected);
    const bool protected_again=VirtualProtect(entry.slot,sizeof(void*),old,&temp)!=0;
    return found==expected && protected_again;
}
bool filter(void* data,UINT bytes,bool active,bool hold=true){
    if(!active || !data || bytes<sizeof(RAWINPUTHEADER)+sizeof(RAWMOUSE))return false;
    auto* raw=static_cast<RAWINPUT*>(data);
    if(raw->header.dwType!=RIM_TYPEMOUSE || raw->header.dwSize<sizeof(RAWINPUTHEADER)+sizeof(RAWMOUSE) ||
        raw->header.dwSize>bytes)return false;
    // Releases still reach DL2 so enabling F8 cannot leave an old native block held.
    raw->data.mouse.usButtonFlags&=~(RI_MOUSE_LEFT_BUTTON_DOWN|RI_MOUSE_RIGHT_BUTTON_DOWN);
    if(hold && !(raw->data.mouse.usFlags&MOUSE_MOVE_ABSOLUTE))raw->data.mouse.lLastX=raw->data.mouse.lLastY=0;
    return true;
}
UINT WINAPI raw_hook(HRAWINPUT handle,UINT command,LPVOID data,PUINT size,UINT header){
    const auto result=original_raw(handle,command,data,size,header);calls.fetch_add(1);
    if(command==RID_INPUT && result!=UINT(-1) && filter(data,result,forwarding(),locking()))filtered.fetch_add(1);
    return result;
}
UINT WINAPI buffer_hook(PRAWINPUT data,PUINT size,UINT header){
    const UINT capacity=size?*size:0;const auto result=original_buffer(data,size,header);calls.fetch_add(1);
    if(result!=UINT(-1) && result<=4096 && data && forwarding()){
        UINT offset=0;
        for(UINT i=0;i<result;++i){
            if(offset>capacity || capacity-offset<sizeof(RAWINPUTHEADER))break;
            auto* raw=reinterpret_cast<RAWINPUT*>(reinterpret_cast<BYTE*>(data)+offset);
            if(raw->header.dwSize<sizeof(RAWINPUTHEADER) || raw->header.dwSize>capacity-offset)break;
            if(filter(raw,raw->header.dwSize,true,locking()))filtered.fetch_add(1);
            const UINT stride=(raw->header.dwSize+sizeof(void*)-1)&~(sizeof(void*)-1);
            if(stride>capacity-offset)break;offset+=stride;
        }
    }
    return result;
}
DWORD WINAPI worker(void*){
    static wchar_t directory[32768]{},path[32768]{},image[32768]{};GetModuleFileNameW(own,directory,32768);
    auto* slash=wcsrchr(directory,L'\\');if(!slash)return 1;*slash=0;
    const DWORD pid=GetCurrentProcessId();GetModuleFileNameW(nullptr,image,32768);const auto* name=wcsrchr(image,L'\\');
    if(!name || _wcsicmp(name+1,L"DyingLightGame_x64_rwdi.exe"))return 2;
    const unsigned char eh[32]={0xa0,0x65,0x19,0xee,0x1f,0xd7,0x9d,0xe1,0xd6,0x65,0x21,0x5f,0x38,0xe6,0xb8,0x9f,0x2b,0x07,0x4b,0xf9,0x74,0x59,0x12,0xc6,0x4a,0x6f,0x06,0x84,0x61,0x7a,0xdb,0x63};
    if(!hash_matches(GetModuleHandleW(L"engine_x64_rwdi.dll"),eh))return 3;
    const unsigned char gh[32]={0xb4,0x17,0x21,0x3b,0x3b,0x1e,0x70,0xb9,0xbb,0x58,0x9b,0x88,0xd3,0x88,0xbb,0x99,0xdd,0x21,0x3b,0x90,0x82,0xd4,0x4e,0xf3,0x8f,0x40,0x21,0x14,0x6f,0x6e,0xe6,0xc4};
    auto engine=GetModuleHandleW(L"engine_x64_rwdi.dll"),game=GetModuleHandleW(L"gamedll_ph_x64_rwdi.dll");
    if(!hash_matches(game,gh))return 3;
    swprintf(path,32768,L"%ls\\native-camera-lock-%lu.config",directory,pid);Config cfg{};
    FILE* f=_wfopen(path,L"rb");bool ok=f && fread(&cfg,1,sizeof(cfg),f)==sizeof(cfg) && fgetc(f)==EOF;if(f)fclose(f);
    if(!ok || cfg.magic!=0x314c4648 || cfg.pid!=pid || !cfg.session)return 4;
    static wchar_t lease_path[32768]{},input_path[32768]{},stop_path[32768]{},log_path[32768]{};
    swprintf(lease_path,32768,L"%ls\\native-axe-session-%lu.lease",directory,pid);
    swprintf(input_path,32768,L"%ls\\guest-input-%016llx.txt",directory,cfg.session);
    swprintf(stop_path,32768,L"%ls\\native-camera-lock-stop-%lu.txt",directory,pid);
    swprintf(log_path,32768,L"%ls\\native-camera-lock-%lu.log",directory,pid);
    halflight_guard::LeaseGuard guard;
    halflight_guard::Lease lease{};DWORD got=0;
    HANDLE file=CreateFileW(lease_path,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
    bool read_ok=file!=INVALID_HANDLE_VALUE && ReadFile(file,&lease,sizeof(lease),&got,nullptr) && got==sizeof(lease);
    if(file!=INVALID_HANDLE_VALUE)CloseHandle(file);
    if(!guard.update(read_ok?&lease:nullptr,GetTickCount64(),pid,cfg.session))return 5;
    auto user=GetModuleHandleW(L"user32.dll");void* raw=reinterpret_cast<void*>(GetProcAddress(user,"GetRawInputData"));void* buffer=reinterpret_cast<void*>(GetProcAddress(user,"GetRawInputBuffer"));
    auto* async_slot=reinterpret_cast<void**>(reinterpret_cast<BYTE*>(engine)+0x180bb28);
    auto* key_slot=reinterpret_cast<void**>(reinterpret_cast<BYTE*>(engine)+0x180b9a8);
    auto* keyboard_slot=reinterpret_cast<void**>(reinterpret_cast<BYTE*>(engine)+0x180ba70);
    // EOS owns these imports in the current lab. Chain the verified original
    // overlay functions rather than replacing or bypassing the overlay.
    auto overlay=GetModuleHandleW(L"EOSOVH-Win64-Shipping.dll");
    const unsigned char oh[32]={0x74,0x33,0x86,0xb1,0x34,0x09,0xf0,0x1b,0x13,0x7c,0x1d,0x7d,0x57,0x56,0x3c,0xcf,0x16,0x45,0x1e,0x43,0x77,0xd3,0xd7,0x1c,0xcd,0xe4,0xcc,0x29,0x0c,0x9f,0xfa,0xc5};
    const bool system_imports=*async_slot==reinterpret_cast<void*>(GetProcAddress(user,"GetAsyncKeyState")) &&
        *key_slot==reinterpret_cast<void*>(GetProcAddress(user,"GetKeyState")) && *keyboard_slot==reinterpret_cast<void*>(GetProcAddress(user,"GetKeyboardState"));
    const bool overlay_imports=overlay && hash_matches(overlay,oh) &&
        *async_slot==reinterpret_cast<BYTE*>(overlay)+0x23f70 && *key_slot==reinterpret_cast<BYTE*>(overlay)+0x240a0 && *keyboard_slot==reinterpret_cast<BYTE*>(overlay)+0x240b0;
    if(!system_imports && !overlay_imports)return 11;
    original_async=reinterpret_cast<KeyFn>(*async_slot);original_key=reinterpret_cast<KeyFn>(*key_slot);original_keyboard=reinterpret_cast<KeyboardFn>(*keyboard_slot);
    imports[0]={reinterpret_cast<void**>(reinterpret_cast<BYTE*>(engine)+0x180bb28),reinterpret_cast<void*>(original_async),reinterpret_cast<void*>(&async_hook)};
    imports[1]={reinterpret_cast<void**>(reinterpret_cast<BYTE*>(engine)+0x180b9a8),reinterpret_cast<void*>(original_key),reinterpret_cast<void*>(&key_hook)};
    imports[2]={reinterpret_cast<void**>(reinterpret_cast<BYTE*>(engine)+0x180ba70),reinterpret_cast<void*>(original_keyboard),reinterpret_cast<void*>(&keyboard_hook)};
    for(const auto& entry:imports)if(!entry.original || *entry.slot!=entry.original)return 11;
    if(!raw || !buffer || memcmp(raw,cfg.raw_prefix,32) || memcmp(buffer,cfg.buffer_prefix,32) || MH_Initialize()!=MH_OK)return 6;
    if(MH_CreateHook(raw,reinterpret_cast<void*>(&raw_hook),reinterpret_cast<void**>(&original_raw))!=MH_OK)return 7;
    if(MH_CreateHook(buffer,reinterpret_cast<void*>(&buffer_hook),reinterpret_cast<void**>(&original_buffer))!=MH_OK){MH_RemoveHook(raw);return 8;}
    HMODULE pin=nullptr;if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,reinterpret_cast<LPCWSTR>(&raw_hook),&pin))return 9;
    MH_QueueEnableHook(raw);MH_QueueEnableHook(buffer);
    if(MH_ApplyQueued()!=MH_OK){MH_DisableHook(raw);MH_DisableHook(buffer);return 10;}
    unsigned installed=0;
    for(;installed<3;++installed)if(!replace_import(imports[installed],false))break;
    if(installed!=3){while(installed)replace_import(imports[--installed],true);MH_DisableHook(raw);MH_DisableHook(buffer);return 12;}
    ULONGLONG last_log=0;const char* reason="requested";halflight_guard::InputLockGuard input_guard;
    while(GetFileAttributesW(stop_path)==INVALID_FILE_ATTRIBUTES){
        const auto now=GetTickCount64();lease={};got=0;
        file=CreateFileW(lease_path,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
        read_ok=file!=INVALID_HANDLE_VALUE && ReadFile(file,&lease,sizeof(lease),&got,nullptr) && got==sizeof(lease) && GetFileSize(file,nullptr)==sizeof(lease);
        if(file!=INVALID_HANDLE_VALUE)CloseHandle(file);
        if(!guard.update(read_ok?&lease:nullptr,now,pid,cfg.session)){reason="lease_expired";break;}
        char text[1024]{};f=_wfopen(input_path,L"rb");if(f){fread(text,1,sizeof(text)-1,f);fclose(f);}
        halflight_guard::InputPacket controls{};
        const bool complete=halflight_guard::parse_input(text,cfg.session,std::time(nullptr),controls);
        if(!complete)missed_reads.fetch_add(1);
        const bool fresh=input_guard.update(complete,controls.sequence,controls.enabled==1,now);
        valid_until.store(now+250);enabled.store(fresh);
        if(now-last_log>=250){last_log=now;f=_wfopen(log_path,L"wb");if(f){fprintf(f,"status,active\nforwarding,%d\nleft_click_lock,%d\nraw_calls,%llu\nfiltered_packets,%llu\nmissed_input_reads,%llu\n",fresh?1:0,locking()?1:0,calls.load(),filtered.load(),missed_reads.load());fclose(f);}}
        Sleep(8);
    }
    enabled.store(false);valid_until.store(0);
    const auto raw_restored=MH_DisableHook(raw),buffer_restored=MH_DisableHook(buffer);
    bool restored=raw_restored==MH_OK && buffer_restored==MH_OK;
    for(auto& entry:imports){const bool ok=replace_import(entry,true);restored=ok && restored;}
    // Keep trampolines and this module resident for callbacks already in flight.
    f=_wfopen(log_path,L"wb");if(f){fprintf(f,"status,stopped\nreason,%s\nhooks_restored,%d\nfiltered_packets,%llu\n",reason,restored?1:0,filtered.load());fclose(f);}return 0;
}
}
#ifdef HALFLIGHT_CAMERA_FILTER_FIXTURE
int main(){RAWINPUT mouse{};mouse.header.dwSize=sizeof(mouse);mouse.header.dwType=RIM_TYPEMOUSE;
    halflight_guard::InputPacket packet{};
    const char* text="Session=0123456789abcdef\nseq=1\nend_seq=1\nexpires_at=101\nenabled=1\nright_guard=1\nleft_guard=1\nmouse_x=-2\nmouse_y=3\n";
    if(!halflight_guard::parse_input(text,0x0123456789abcdef,100,packet) || !packet.left || !packet.right ||
       halflight_guard::parse_input(text,2,100,packet) || halflight_guard::parse_input(text,0x0123456789abcdef,102,packet))return 24;
    char duplicate[512]{};snprintf(duplicate,sizeof(duplicate),"%senabled=0\n",text);
    if(halflight_guard::parse_input(duplicate,0x0123456789abcdef,100,packet))return 25;
    char modifier[512]{};snprintf(modifier,sizeof(modifier),"%salt=1\n",text);
    if(!halflight_guard::parse_input(modifier,0x0123456789abcdef,100,packet))return 26;
    snprintf(modifier,sizeof(modifier),"%salt=2\n",text);
    if(halflight_guard::parse_input(modifier,0x0123456789abcdef,100,packet))return 27;
    snprintf(modifier,sizeof(modifier),"%salt=1\nalt=0\n",text);
    if(halflight_guard::parse_input(modifier,0x0123456789abcdef,100,packet))return 28;
    snprintf(modifier,sizeof(modifier),"%salt=1\nswap=1\n",text);
    if(!halflight_guard::parse_input(modifier,0x0123456789abcdef,100,packet))return 29;
    snprintf(modifier,sizeof(modifier),"%salt=1\nswap=2\n",text);
    if(halflight_guard::parse_input(modifier,0x0123456789abcdef,100,packet))return 30;
    snprintf(modifier,sizeof(modifier),"%salt=1\nswap=1\nswap=0\n",text);
    if(halflight_guard::parse_input(modifier,0x0123456789abcdef,100,packet))return 31;
    halflight_guard::InputLockGuard guard;
    if(!guard.update(true,1,true,1000) || !guard.update(false,0,false,1100) || guard.update(false,0,false,1250))return 20;
    if(!guard.update(true,2,true,1300) || guard.update(true,3,false,1301))return 21;
    if(!guard.update(true,4,true,1400) || !guard.update(true,4,true,1500) || guard.update(true,4,true,1650))return 22;
    if(!guard.update(true,5,true,1700) || guard.update(true,4,true,1701))return 23;
    mouse.data.mouse.lLastX=23;mouse.data.mouse.lLastY=-41;mouse.data.mouse.usButtonFlags=RI_MOUSE_LEFT_BUTTON_DOWN|RI_MOUSE_WHEEL;mouse.data.mouse.usButtonData=120;
    auto original=mouse;if(filter(&mouse,sizeof(mouse),false) || memcmp(&mouse,&original,sizeof(mouse)))return 1;
    if(!filter(&mouse,sizeof(mouse),true) || mouse.data.mouse.lLastX || mouse.data.mouse.lLastY || mouse.data.mouse.usButtonFlags!=RI_MOUSE_WHEEL || mouse.data.mouse.usButtonData!=120)return 2;
    mouse=original;mouse.data.mouse.usFlags=MOUSE_MOVE_ABSOLUTE;if(!filter(&mouse,sizeof(mouse),true) || mouse.data.mouse.lLastX!=23 || mouse.data.mouse.lLastY!=-41 || mouse.data.mouse.usButtonFlags!=RI_MOUSE_WHEEL)return 3;
    mouse=original;mouse.header.dwType=RIM_TYPEKEYBOARD;auto keyboard=mouse;if(filter(&mouse,sizeof(mouse),true) || memcmp(&mouse,&keyboard,sizeof(mouse)))return 4;
    mouse=original;if(filter(&mouse,sizeof(RAWINPUTHEADER),true) || filter(nullptr,sizeof(mouse),true))return 5;
    mouse.header.dwSize=sizeof(mouse)+1;if(filter(&mouse,sizeof(mouse),true))return 6;
    mouse=original;mouse.data.mouse.usButtonFlags=RI_MOUSE_LEFT_BUTTON_DOWN|RI_MOUSE_RIGHT_BUTTON_DOWN|RI_MOUSE_LEFT_BUTTON_UP|RI_MOUSE_RIGHT_BUTTON_UP|RI_MOUSE_MIDDLE_BUTTON_DOWN|RI_MOUSE_WHEEL;
    if(!filter(&mouse,sizeof(mouse),true,false) || mouse.data.mouse.lLastX!=23 || mouse.data.mouse.lLastY!=-41 || mouse.data.mouse.usButtonFlags!=(RI_MOUSE_LEFT_BUTTON_UP|RI_MOUSE_RIGHT_BUTTON_UP|RI_MOUSE_MIDDLE_BUTTON_DOWN|RI_MOUSE_WHEEL) || mouse.data.mouse.usButtonData!=120)return 7;
    if(filter_key(VK_LBUTTON,SHORT(0x8001),true) || filter_key(VK_RBUTTON,SHORT(0x8001),true) || filter_key(VK_LBUTTON,SHORT(0x8001),false)!=SHORT(0x8001) || filter_key('W',SHORT(0x8001),true)!=SHORT(0x8001))return 8;
    void* value=reinterpret_cast<void*>(1);InputImport entry{&value,value,reinterpret_cast<void*>(2)};
    if(!replace_import(entry,false) || value!=entry.replacement || replace_import(entry,false) || !replace_import(entry,true) || value!=entry.original)return 9;
    value=reinterpret_cast<void*>(3);if(replace_import(entry,false) || value!=reinterpret_cast<void*>(3))return 10;
    puts("camera_filter_passed: F8 attack/block downs and host polling suppressed; off, releases, other buttons, wheel, keyboard and absolute motion preserved; owned imports restored");return 0;}
#else
BOOL WINAPI DllMain(HINSTANCE module,DWORD reason,LPVOID){if(reason==DLL_PROCESS_ATTACH){own=module;DisableThreadLibraryCalls(module);HANDLE thread=CreateThread(nullptr,0,worker,nullptr,0,nullptr);if(thread)CloseHandle(thread);}return TRUE;}
#endif
