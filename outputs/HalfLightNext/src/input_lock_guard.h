#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>
namespace halflight_guard {
struct InputPacket {std::uint64_t session=0,sequence=0;long long expiry=0;int enabled=0,right=0,left=0;};
inline bool parse_input(const char* text,std::uint64_t session,long long unix,InputPacket& out){
    unsigned long long nonce=0,seq=0,end=0;long long expiry=0,x=0,y=0;int armed=0,right=0,left=0,used=0;
    const int fields=std::sscanf(text,"Session=%16llx\nseq=%llu\nend_seq=%llu\nexpires_at=%lld\nenabled=%d\nright_guard=%d\nleft_guard=%d\nmouse_x=%lld\nmouse_y=%lld\n%n",
        &nonce,&seq,&end,&expiry,&armed,&right,&left,&x,&y,&used);
    if(fields!=9 || !used || nonce!=session || !seq || seq!=end || expiry<unix || expiry>unix+1 ||
        (armed!=0 && armed!=1) || (right!=0 && right!=1) || (left!=0 && left!=1))return false;
    if(text[used]){
        int alt=0,tail=0;
        if(std::sscanf(text+used,"alt=%d\n%n",&alt,&tail)!=1 || !tail || (alt!=0 && alt!=1))return false;
        used+=tail;
        if(text[used]){
            int swap=0;tail=0;
            if(std::sscanf(text+used,"swap=%d\n%n",&swap,&tail)!=1 || !tail ||
                std::size_t(used+tail)!=std::strlen(text) || (swap!=0 && swap!=1))return false;
        }
    }
    out={nonce,seq,expiry,armed,right,left};return true;
}
// Missing/torn transport is not an explicit release. It never extends a lease.
class InputLockGuard {
    std::uint64_t deadline=0,sequence=0;
    bool forwarding=false;
public:
    bool update(bool complete,std::uint64_t seq,bool armed,std::uint64_t now){
        if(complete){
            if(seq<sequence){deadline=0;forwarding=false;return false;}
            if(seq>sequence){sequence=seq;deadline=now+250;forwarding=armed;}
            // An explicit off packet must release even if its sequence repeats.
            if(!armed){forwarding=false;deadline=0;}
        }
        return forwarding && now<deadline;
    }
};
}
