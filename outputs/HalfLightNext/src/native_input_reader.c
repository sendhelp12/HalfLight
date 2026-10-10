/* Game-mod input companion: observes physical input; never injects Windows events. */
#include <windows.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <assert.h>
static char folder[2048],session[17];
static DWORD target_pid;
static ULONGLONG deadline;
static long long mouse_x,mouse_y;
static unsigned long long sequence,active_packets;
static int enabled,last_toggle;
static int continuous;
static ULONGLONG stop_started;
static int stop_requested(ULONGLONG now,int chord) {
    if(!chord){stop_started=0;return 0;}
    if(!stop_started)stop_started=now;
    return now-stop_started>=1500;
}
static FILE* stream;
static void stream_publish(const char* text) {
    if(!stream){char path[2200];snprintf(path,sizeof(path),"%s\\guest-input-%s.stream",folder,session);stream=fopen(path,"w+b");if(!stream)return;setvbuf(stream,NULL,_IONBF,0);}
    uint32_t a=1,b=0;size_t size=strlen(text);
    for(size_t i=0;i<size;++i){a=(a+(unsigned char)text[i])%65521;b=(b+a)%65521;}
    char header[40],footer[23];
    int h=snprintf(header,sizeof(header),"HLS1,%016llu,%05u,%010u\n",sequence,(unsigned)size,b*65536+a);
    int f=snprintf(footer,sizeof(footer),"HLS1,%016llu\n",sequence);
    if(h!=39 || f!=22 || size>4096)return;
    if(fseek(stream,0,SEEK_SET) || fwrite("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!",1,39,stream)!=39 ||
       fwrite(text,1,size,stream)!=size || fwrite(footer,1,22,stream)!=22 || fseek(stream,0,SEEK_SET) || fwrite(header,1,39,stream)!=39){fclose(stream);stream=NULL;}
}
#pragma pack(push,1)
struct lease_packet {uint32_t magic,pid;uint64_t nonce,expires_ms;};
#pragma pack(pop)
static ULONGLONG lease_deadline;
static int lease_update(const struct lease_packet* value,ULONGLONG now) {
    if(value) {
        if(value->magic!=0x31534648 || value->pid!=target_pid || value->nonce!=strtoull(session,NULL,16) || value->expires_ms<=now || value->expires_ms>now+10000){lease_deadline=0;return 0;}
        lease_deadline=value->expires_ms;
    }
    return lease_deadline>now; /* A missed read never extends the issued deadline. */
}
static int lease_alive(void) {
    char path[2200];snprintf(path,sizeof(path),"%s\\native-axe-session-%lu.lease",folder,(unsigned long)target_pid);
    HANDLE file=CreateFileA(path,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL);
    if(file==INVALID_HANDLE_VALUE)return lease_update(NULL,GetTickCount64());
    struct lease_packet value;DWORD got=0;
    int read=ReadFile(file,&value,sizeof(value),&got,NULL);
    int size_ok=got==sizeof(value) && GetFileSize(file,NULL)==sizeof(value);
    CloseHandle(file);ULONGLONG now=GetTickCount64();
    if(!read)return lease_update(NULL,now);
    if(!size_ok){lease_deadline=0;return 0;}
    return lease_update(&value,now);
}
static int foreground(void){DWORD pid=0;GetWindowThreadProcessId(GetForegroundWindow(),&pid);return pid==target_pid;}
static int down(int key){return (GetAsyncKeyState(key)&0x8000)!=0;}
static void publish(int ending) {
    int active=0;
    if(!ending && foreground()) {
        int toggle=down(VK_F8);if(toggle && !last_toggle)enabled=!enabled;
        last_toggle=toggle;if(down(VK_ESCAPE))enabled=0;active=enabled;
    } else {enabled=0;last_toggle=0;}
    char path[2200],temporary[2200];
    snprintf(path,sizeof(path),"%s\\guest-input-%s.txt",folder,session);
    snprintf(temporary,sizeof(temporary),"%s\\guest-input-%s.tmp",folder,session);
    FILE* f=fopen(temporary,"wb");if(!f)return;
    ++sequence;if(active)++active_packets;
    char text[1024];snprintf(text,sizeof(text),"Session=%s\nseq=%llu\nend_seq=%llu\nexpires_at=%lld\nenabled=%d\nright_guard=%d\nleft_guard=%d\nmouse_x=%lld\nmouse_y=%lld\nalt=%d\nswap=%d\n",
        session,sequence,sequence,(long long)time(NULL)+1,active,active?down(VK_LBUTTON):0,active?down(VK_RBUTTON):0,mouse_x,mouse_y,active?down(VK_MENU):0,active?down('X'):0);
    stream_publish(text);fputs(text,f);
    fclose(f);
    /* The committed stream is already fresh. Retry status publication on the
       next timer; never block physical mouse collection on another reader. */
    MoveFileExA(temporary,path,MOVEFILE_REPLACE_EXISTING);
}
static LRESULT CALLBACK proc(HWND window,UINT message,WPARAM wparam,LPARAM lparam) {
    if(message==WM_INPUT && enabled && foreground()) {
        RAWINPUT raw;UINT bytes=sizeof(raw);
        if(GetRawInputData((HRAWINPUT)lparam,RID_INPUT,&raw,&bytes,sizeof(RAWINPUTHEADER))!=(UINT)-1 &&
           raw.header.dwType==RIM_TYPEMOUSE && !(raw.data.mouse.usFlags&MOUSE_MOVE_ABSOLUTE)) {
            mouse_x+=raw.data.mouse.lLastX;mouse_y+=raw.data.mouse.lLastY;
        }
    } else if(message==WM_TIMER) {
        if(continuous && stop_requested(GetTickCount64(),foreground() && down(VK_F8) && down(VK_SHIFT) && down(VK_CONTROL))) {
            char path[2200];snprintf(path,sizeof(path),"%s\\guest-stop-%s.txt",folder,session);
            FILE* stop=fopen(path,"wb");if(stop){fputs("deliberate Ctrl+Shift+F8 stop\n",stop);fclose(stop);}
            publish(1);PostQuitMessage(0);
        } else if((continuous && !lease_alive()) || (!continuous && GetTickCount64()>=deadline)){publish(1);PostQuitMessage(0);}else publish(0);
    }
    return DefWindowProcW(window,message,wparam,lparam);
}
int main(int argc,char** argv) {
    if(argc==2 && !strcmp(argv[1],"--stop-fixture")){
        assert(!stop_requested(1000,0));assert(!stop_requested(1100,1));
        assert(!stop_requested(2599,1));assert(stop_requested(2600,1));
        assert(!stop_requested(2700,0));assert(!stop_requested(2800,1));
        assert(!stop_requested(2900,0));assert(!stop_requested(5000,1));
        puts("PASS stop chord requires Ctrl+Shift+F8 held 1500ms; release resets its timer.");return 0;
    }
    if(argc==2 && !strcmp(argv[1],"--lease-fixture")){
        target_pid=123;strcpy(session,"0123456789abcdef");
        struct lease_packet value={0x31534648,123,0x0123456789abcdef,2000};
        assert(!lease_update(NULL,1000));assert(lease_update(&value,1000));
        assert(lease_update(NULL,1999));assert(!lease_update(NULL,2000));
        assert(lease_update(&value,1000));value.expires_ms=0;assert(!lease_update(&value,1000));assert(!lease_update(NULL,1001));
        value.expires_ms=12000;assert(!lease_update(&value,1000));
        value.expires_ms=2000;value.nonce++;assert(!lease_update(&value,1000));
        puts("PASS native input lease: missed reads retain only the issued deadline; expiry, revocation, wrong session and oversized deadline refuse.");return 0;
    }
    if(argc==3 && !strcmp(argv[1],"--publish-fixture")){
        if(strlen(argv[2])>=sizeof(folder))return 2;
        strcpy(folder,argv[2]);strcpy(session,"0123456789abcdef");
        char path[2200];snprintf(path,sizeof(path),"%s\\guest-input-%s.txt",folder,session);
        HANDLE locked=CreateFileA(path,GENERIC_READ|GENERIC_WRITE,0,NULL,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,NULL);
        if(locked==INVALID_HANDLE_VALUE)return 3;
        ULONGLONG began=GetTickCount64();for(int i=0;i<20;++i)publish(1);
        ULONGLONG elapsed=GetTickCount64()-began;CloseHandle(locked);
        if(!stream || sequence!=20 || elapsed>=200)return 4;
        publish(1);FILE* committed=fopen(path,"rb");if(!committed)return 5;
        char text[1024]={0};fread(text,1,sizeof(text)-1,committed);fclose(committed);fclose(stream);
        if(!strstr(text,"seq=21\n"))return 6;
        puts("PASS locked status file does not stall input stream; next publication recovers.");return 0;
    }
    if(argc==3 && !strcmp(argv[1],"--stream-fixture")){
        if(strlen(argv[2])>=sizeof(folder))return 2;
        strcpy(folder,argv[2]);strcpy(session,"0123456789abcdef");sequence=1;
        stream_publish("first\n");sequence=2;stream_publish("second\n");if(!stream)return 3;fclose(stream);return 0;
    }
    if((argc!=4 && argc!=5) || strlen(argv[1])>=sizeof(folder) || strlen(argv[3])!=16)return 2;
    if(argc==5){if(strcmp(argv[4],"continuous"))return 2;continuous=1;}
    for(int i=0;i<16;++i)if(!strchr("0123456789abcdef",argv[3][i]))return 3;
    target_pid=(DWORD)strtoul(argv[2],NULL,10);if(!target_pid)return 4;
    strcpy(folder,argv[1]);strcpy(session,argv[3]);deadline=GetTickCount64()+40000;
    HINSTANCE instance=GetModuleHandleW(NULL);WNDCLASSW c={0};c.hInstance=instance;c.lpfnWndProc=proc;c.lpszClassName=L"HalfLightNativeInputReader";
    if(!RegisterClassW(&c))return 5;
    HWND window=CreateWindowExW(0,c.lpszClassName,L"",0,0,0,0,0,HWND_MESSAGE,NULL,instance,NULL);
    RAWINPUTDEVICE device={1,2,RIDEV_INPUTSINK,window};
    if(!window || !RegisterRawInputDevices(&device,1,sizeof(device)) || !SetTimer(window,1,16,NULL))return 6;
    puts(continuous?"Ready: F8 forwards mouse; Escape disables; hold Ctrl+Shift+F8 1.5 seconds to end the session. Controller heartbeat required.":"Ready: F8 forwards mouse; Escape disables. Bounded to 40 seconds.");fflush(stdout);
    MSG message;while(GetMessageW(&message,NULL,0,0)>0){TranslateMessage(&message);DispatchMessageW(&message);}
    KillTimer(window,1);DestroyWindow(window);
    if(stream)fclose(stream);
    printf("input_reader_finished,active_packets,%llu\n",active_packets);return 0;
}
