// Installed HumanHealthModule: slot 276 reads life, slot 289 tests life <= 0.
// Look up the module again from the occupied entity; never retain a corpse's AI.
struct NativeHealth {
    using GetHealth=float(*)(const void*);
    GetHealth get=nullptr;
    bool read_health(const Binding& b,float& value) const {
        if(!get || !binding_valid(b))return false;
        std::uint64_t packed=0;std::uint32_t count=0;
        if(!read_at(b.entity+0x78,packed))return false;
        const auto data=packed&0xffffffffffffull;const auto small=unsigned(packed>>56);
        if(small)count=small-1;else if(!read_at(b.entity+0x80,count))return false;
        if(!count || count>=256)return false;
        const auto arena=b.entity-((b.entity_handle<<4)&0xffffffffull);
        for(unsigned i=0;i<count;++i){
            std::uint64_t handle=0,found=0;std::uintptr_t table=0,owner=0,human=0,registry=0,module=0,tuple_slot=0,tuple=0;
            if(!read_at(data+i*8,handle))return false;
            const auto component=arena+((handle<<4)&0xffffffffull);
            if(!read_at(component+8,found) || handle!=found || !occupied(component,handle) ||
               !read_at(component,table) || table!=game+0x281f270)continue;
            if(!read_at(component+0x10,owner) || owner!=b.entity || !read_at(component+0x78,human) ||
               !read_at(human,table) || table!=game+0x293ba38 || !read_at(human+0x608,registry) ||
               !read_at(registry+0x70,module) || !read_at(module,table) || table!=game+0x280e690 ||
               !read_at(module+8,owner) || (owner&0x1fffffffffffffffull)!=human+0x80 ||
               !read_at(module+0x18,tuple_slot) || !read_at(tuple_slot,tuple) || !tuple)return false;
            value=get(reinterpret_cast<const void*>(module));
            return std::isfinite(value) && value>=-1000000 && value<=10000000;
        }
        return false;
    }
};
