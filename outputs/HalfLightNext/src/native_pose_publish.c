#include <windows.h>
#include <string.h>
/* Original shared-memory publisher. The native consumer opens read-only. */
__declspec(dllexport) void HLF_Publish(void* view,const void* packet,LONG stamp) {
    if(!view || !packet || stamp<=0 || (stamp&1))return;
    InterlockedExchange((volatile LONG*)view,stamp-1);
    memcpy((unsigned char*)view+8,packet,80);
    InterlockedExchange((volatile LONG*)view,stamp);
}
