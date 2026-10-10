#pragma once
// Native copies rebuild the cache; route the owned terms, not the cached result.
bool route_melee_factor(unsigned char* fields,float scale,unsigned source,unsigned destination){
    if((source!=0 && source!=1 && source!=2 && source!=13) || (destination!=1 && destination!=2) ||
       !std::isfinite(scale) || scale<0 || scale>1000000)return false;
    float values[3]{};std::memcpy(values,fields+source*16+4,12);
    for(float& value:values){
        if(!std::isfinite(value) || std::abs(value)>1000000)return false;
        value*=scale;if(!std::isfinite(value) || std::abs(value)>1000000)return false;
    }
    if(source!=destination){
        unsigned char original[16];std::memcpy(original,fields+destination*16,16);
        std::memcpy(fields+destination*16,fields+source*16,16);std::memcpy(fields+source*16,original,16);
    }
    std::memcpy(fields+destination*16+4,values,12);return true;
}
bool scale_owned_melee(std::uintptr_t container,float scale,unsigned source,unsigned destination){
    using Convert=void*(*)(unsigned,const void*,void*);
    using Resolve=void(*)(void*,float);
    using Id=unsigned(*)(const void*);using Time=float(*)(const void*);
    using Insert=void(*)(void*,void*,const void*,const void*);
    using Clear=void(*)(void*);
    struct Row {unsigned char fields[0x110];};
    alignas(16) Row rows[128]{};unsigned used=0;
    std::uintptr_t id_address=0,time_address=0;
    if(!read_at(game+0x23f7458,id_address) || !read_at(game+0x23f7460,time_address) || !id_address || !time_address)return false;
    for(unsigned group=0;group<2;++group){
        std::uint64_t packed=0;unsigned count=0;const auto offset=group?0x340u:8u;
        if(!read_at(container+offset,packed))return false;
        if(packed>>56)count=unsigned(packed>>56)-1;else if(!read_at(container+offset+8,count))return false;
        if(count>64 || used+count>128)return false;
        const auto data=packed&0xffffffffffffull;
        for(unsigned i=0;i<count;++i){
            auto& row=rows[used++];float progress=0;
            if(!group){if(!read(reinterpret_cast<void*>(data+i*0x110),&row,sizeof(row)))return false;std::memcpy(&progress,row.fields+0x10c,4);}
            else {
                const auto pair=reinterpret_cast<void*>(data+i*8);
                const unsigned key=reinterpret_cast<Id>(id_address)(pair);progress=reinterpret_cast<Time>(time_address)(pair);
                reinterpret_cast<Convert>(game+0x96b9d0)(key,reinterpret_cast<void*>(game+0x374cdf8),&row);
                std::memcpy(row.fields+0x10c,&progress,4);
            }
            if(!std::isfinite(progress) || std::abs(progress)>100000)return false;
            for(unsigned channel=0;channel<16;++channel){
                reinterpret_cast<Resolve>(game+0x1ef2180)(row.fields+channel*16,progress);
            }
            // Installed DamageFactors registers Cut at 0x20 and Ram at 0xd0.
            if(!route_melee_factor(row.fields,scale,source,destination))return false;
        }
    }
    if(!used)return false;
    reinterpret_cast<Clear>(game+0xa853e0)(reinterpret_cast<void*>(container));
    for(unsigned i=0;i<used;++i){
        std::uint64_t packed=0;unsigned count=0;if(!read_at(container+8,packed))return false;
        if(packed>>56)count=unsigned(packed>>56)-1;else if(!read_at(container+16,count))return false;
        const auto end=(packed&0xffffffffffffull)+count*0x110;
        reinterpret_cast<Insert>(game+0xa57940)(reinterpret_cast<void*>(container+8),reinterpret_cast<void*>(end),&rows[i],&rows[i+1]);
    }
    return true;
}
