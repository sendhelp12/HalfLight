// Original, observation-only adapter for the pinned Developer Tools build.
// No mesh setters, pose writes, instruction patches, trampolines or unloading.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wincrypt.h>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cwchar>

namespace {
using Update = void(*)(void*);
#ifndef HALFLIGHT_OBSERVER_FIXTURE
constexpr std::uintptr_t table_rva=0x250aec8, slot_offset=0x878;
constexpr std::uintptr_t expected_thunk_rva=0x1d76348;
#endif
constexpr DWORD duration_ms=5000;
struct Event { DWORD thread; std::uintptr_t self; LONGLONG counter; };
Event events[2048]{};
std::atomic<unsigned> count{0}, in_flight{0};
std::atomic<bool> active{false};
Update original=nullptr;
void** slot=nullptr;
HMODULE own_module=nullptr;
ULONGLONG deadline=0;

bool hash_matches(HMODULE module,const unsigned char* expected) {
    wchar_t path[32768]{};
    if(!GetModuleFileNameW(module,path,32768))return false;
    HANDLE file=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(file==INVALID_HANDLE_VALUE)return false;
    HCRYPTPROV provider=0;HCRYPTHASH hash=0;
    bool ok=CryptAcquireContextW(&provider,nullptr,nullptr,PROV_RSA_AES,CRYPT_VERIFYCONTEXT)!=0;
    if(ok)ok=CryptCreateHash(provider,CALG_SHA_256,0,0,&hash)!=0;
    unsigned char buffer[65536]{};DWORD bytes=0;
    while(ok) {
        if(!ReadFile(file,buffer,sizeof(buffer),&bytes,nullptr)){ok=false;break;}
        if(!bytes)break;
        if(!CryptHashData(hash,buffer,bytes,0)){ok=false;break;}
    }
    unsigned char actual[32]{};DWORD size=sizeof(actual);
    if(ok)ok=CryptGetHashParam(hash,HP_HASHVAL,actual,&size,0)!=0 && size==32;
    if(ok)for(unsigned i=0;i<32;++i)if(actual[i]!=expected[i])ok=false;
    if(hash)CryptDestroyHash(hash);if(provider)CryptReleaseContext(provider,0);CloseHandle(file);
    return ok;
}

void observe(void* self) {
    in_flight.fetch_add(1,std::memory_order_acq_rel);
    original(self);
    if(active.load(std::memory_order_acquire) && GetTickCount64()<deadline) {
        const auto index=count.fetch_add(1,std::memory_order_acq_rel);
        if(index<2048) {
            LARGE_INTEGER tick{}; QueryPerformanceCounter(&tick);
            events[index]={GetCurrentThreadId(),reinterpret_cast<std::uintptr_t>(self),tick.QuadPart};
        }
    }
    in_flight.fetch_sub(1,std::memory_order_release);
}

// Exchange only the validated vtable pointer, preserving another owner's patch.
bool exchange_slot(void* desired,void* expected) {
    DWORD prior=0,discard=0;
    if(!VirtualProtect(slot,sizeof(void*),PAGE_READWRITE,&prior))return false;
    void* found=InterlockedCompareExchangePointer(reinterpret_cast<void* volatile*>(slot),desired,expected);
    const bool protected_again=VirtualProtect(slot,sizeof(void*),prior,&discard)!=0;
    return found==expected && protected_again;
}

DWORD WINAPI run(void*) {
    wchar_t own_path[32768]{};
    if(!GetModuleFileNameW(own_module,own_path,32768))return 1;
    wchar_t* slash=wcsrchr(own_path,L'\\');if(!slash)return 2;*slash=0;
    wchar_t path[32768]{};
    if(swprintf(path,32768,L"%ls\\native-update-observation-%lu.csv",own_path,GetCurrentProcessId())<0)return 3;
    FILE* log=_wfopen(path,L"wb");if(!log)return 4;
    HMODULE pin=nullptr;
    // Keep this native callback address valid until process exit, even on failure.
    if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,
                          reinterpret_cast<LPCWSTR>(&observe),&pin)) {
        fputs("status,pin_failed\n",log);fclose(log);return 5;
    }
#ifdef HALFLIGHT_OBSERVER_FIXTURE
    // The fixture supplies an isolated fake table; it never locates a game.
    if(!slot || !original){fputs("status,fixture_uninitialized\n",log);fclose(log);return 6;}
#else
    wchar_t image[32768]{};GetModuleFileNameW(nullptr,image,32768);
    const wchar_t* image_name=wcsrchr(image,L'\\');
    if(!image_name || _wcsicmp(image_name+1,L"DyingLightGame_x64_rwe.exe")!=0) {
        fputs("status,wrong_process\n",log);fclose(log);return 6;
    }
    const auto module=GetModuleHandleW(L"gamedll_ph_x64_rwe.dll");
    if(!module) {fputs("status,module_missing\n",log);fclose(log);return 7;}
    const unsigned char expected_game[32]={0x50,0x25,0x6d,0x51,0x15,0x1e,0xf4,0x5d,0xe2,0x7a,0x73,0x79,0xe3,0x1c,0xe1,0xfc,0xba,0x96,0x15,0x52,0x42,0xea,0xf8,0x35,0xce,0xac,0x22,0xd4,0xcb,0xa9,0xab,0x88};
    const unsigned char expected_engine[32]={0xb3,0x68,0x19,0x44,0xf5,0xdd,0xd9,0x90,0x00,0x6d,0xf8,0xfe,0xb0,0xf9,0x93,0xe7,0x29,0x1e,0x4a,0x58,0x6d,0x0d,0x43,0xf1,0x37,0xad,0x64,0x38,0x0c,0xd5,0x5b,0xc2};
    if(!hash_matches(module,expected_game) || !hash_matches(GetModuleHandleW(L"engine_x64_rwe.dll"),expected_engine)) {
        fputs("status,module_hash_mismatch\n",log);fclose(log);return 13;
    }
    const auto base=reinterpret_cast<std::uintptr_t>(module);
    slot=reinterpret_cast<void**>(base+table_rva+slot_offset);
    MEMORY_BASIC_INFORMATION region{};
    if(!VirtualQuery(slot,&region,sizeof(region)) || region.State!=MEM_COMMIT ||
       region.AllocationBase!=module || (region.Protect&(PAGE_GUARD|PAGE_NOACCESS))) {
        fputs("status,slot_region_invalid\n",log);fclose(log);return 8;
    }
    original=reinterpret_cast<Update>(*slot);
    if(reinterpret_cast<std::uintptr_t>(original)!=base+expected_thunk_rva) {
        fputs("status,original_slot_mismatch\n",log);fclose(log);return 9;
    }
    const auto* thunk=reinterpret_cast<const unsigned char*>(original);
    if(thunk[0]!=0xff || thunk[1]!=0x25) {
        fputs("status,thunk_mismatch\n",log);fclose(log);return 10;
    }
#endif
    deadline=GetTickCount64()+duration_ms;
    active.store(true,std::memory_order_release);
    const bool installed=exchange_slot(reinterpret_cast<void*>(&observe),reinterpret_cast<void*>(original));
    if(!installed) {
        active.store(false,std::memory_order_release);
        const bool reverted=exchange_slot(reinterpret_cast<void*>(original),reinterpret_cast<void*>(&observe));
        fprintf(log,"status,install_failed\nrestored,%d\n",reverted?1:0);fclose(log);return 11;
    }
    while(GetTickCount64()<deadline)Sleep(10);
    active.store(false,std::memory_order_release);
    const bool restored=exchange_slot(reinterpret_cast<void*>(original),reinterpret_cast<void*>(&observe));
    // Code and data stay allocated even if a previously fetched call arrives late.
    const auto drain_limit=GetTickCount64()+100;
    while(in_flight.load(std::memory_order_acquire) && GetTickCount64()<drain_limit)Sleep(1);
    LARGE_INTEGER frequency{};QueryPerformanceFrequency(&frequency);
    const unsigned captured=count.load(std::memory_order_acquire);
    fprintf(log,"status,observation_finished\nrestored,%d\ncalls,%u\nfrequency,%lld\n",
            restored?1:0,captured,static_cast<long long>(frequency.QuadPart));
    if(in_flight.load(std::memory_order_acquire)==0) {
        fputs("thread,self,counter\n",log);
        for(unsigned i=0;i<captured && i<2048;++i)
            fprintf(log,"%lu,0x%llx,%lld\n",events[i].thread,
                    static_cast<unsigned long long>(events[i].self),static_cast<long long>(events[i].counter));
    } else fputs("records,in_flight_not_drained\n",log);
    fputs("complete,1\n",log);fclose(log);return restored?0:12;
}

#ifdef HALFLIGHT_OBSERVER_FIXTURE
std::atomic<unsigned> original_calls{0};
void fixture_original(void*) {original_calls.fetch_add(1,std::memory_order_relaxed);}
DWORD WINAPI fixture_driver(void*) {
    const auto end=GetTickCount64()+duration_ms+250;
    while(GetTickCount64()<end) {
        auto function=reinterpret_cast<Update>(InterlockedCompareExchangePointer(
            reinterpret_cast<void* volatile*>(slot),nullptr,nullptr));
        function(reinterpret_cast<void*>(0x12340000));Sleep(5);
    }
    return 0;
}
#endif
}

BOOL WINAPI DllMain(HINSTANCE module,DWORD reason,void*) {
    if(reason==DLL_PROCESS_ATTACH) {
        own_module=module;DisableThreadLibraryCalls(module);
        // No waiting in DllMain. The worker begins after loader-lock release.
        HANDLE worker=CreateThread(nullptr,0,&run,nullptr,0,nullptr);
        if(worker)CloseHandle(worker);
    }
    return TRUE;
}

#ifdef HALFLIGHT_OBSERVER_FIXTURE
int main(int argc,char** argv) {
    own_module=GetModuleHandleW(nullptr);
    if(argc!=2 || strlen(argv[1])!=64)return 23;
    unsigned char expected[32]{};
    for(unsigned i=0;i<32;++i) {
        unsigned value=0;if(sscanf(argv[1]+i*2,"%2x",&value)!=1)return 24;
        expected[i]=static_cast<unsigned char>(value);
    }
    if(!hash_matches(own_module,expected))return 25;
    expected[0]^=1;if(hash_matches(own_module,expected))return 26;
    slot=static_cast<void**>(VirtualAlloc(nullptr,4096,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE));
    if(!slot)return 20;
    original=&fixture_original;*slot=reinterpret_cast<void*>(original);
    HANDLE driver=CreateThread(nullptr,0,&fixture_driver,nullptr,0,nullptr);
    if(!driver)return 21;
    const DWORD result=run(nullptr);
    WaitForSingleObject(driver,10000);CloseHandle(driver);
    const bool passed=result==0 && *slot==reinterpret_cast<void*>(original) && !active.load() && count.load()>100;
    printf("fixture_only=%d restored=%d callbacks=%u original_calls=%u\n",1,
           *slot==reinterpret_cast<void*>(original)?1:0,count.load(),original_calls.load());
    VirtualFree(slot,0,MEM_RELEASE);return passed?0:22;
}
#endif
