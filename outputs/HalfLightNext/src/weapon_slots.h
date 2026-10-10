#pragma once
#include <cstdint>
namespace halflight_slots {
constexpr unsigned max_types=32,max_banks=2*max_types;
using BankMask=std::uint64_t;
inline BankMask bank_bit(unsigned index){return index<max_banks?BankMask{1}<<index:0;}
inline bool valid_bank_mask(BankMask mask,unsigned banks){return banks && banks<=max_banks && (banks==64 || (mask>>banks)==0);}
inline bool pose_tag(std::uint32_t magic,unsigned types,unsigned& index,bool& present){
    if(!types || types>max_types || (magic&0x00ffffffu)!=0x004c4648u)return false;
    const unsigned code=magic>>24;present=code>=0x33 && code<0x33+max_types;
    if(!present && (code<0x73 || code>=0x73+max_types))return false;
    index=code-(present?0x33u:0x73u);return index<types;
}
}
