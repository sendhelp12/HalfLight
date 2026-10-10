#pragma once
#include <cstdint>
namespace halflight_guard {
struct Lease {std::uint32_t magic,pid;std::uint64_t session,expiry;};
class LeaseGuard {
    std::uint64_t deadline=0;
public:
    bool update(const Lease* packet,std::uint64_t now,std::uint32_t pid,std::uint64_t session){
        if(packet){
            if(packet->magic!=0x31534648 || packet->pid!=pid || packet->session!=session || packet->expiry<=now || packet->expiry>now+10000){deadline=0;return false;}
            deadline=packet->expiry;
        }
        // A missed read never grants extra time; keep only the last issued deadline.
        return deadline>now;
    }
};
}
