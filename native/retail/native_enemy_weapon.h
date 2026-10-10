#pragma once
// Native visual bounds and animated matrices, read on the existing game phase.
// Hidden/stowed inventory entries never become weapon blockers.
struct NativeEnemyWeapons {
    using GetMatrix=const float*(*)(void*,unsigned);
    using GetBounds=const float*(*)(void*);
    GetMatrix matrix=nullptr;GetBounds bounds=nullptr;
    bool type(std::uintptr_t object,std::uintptr_t module,const char* expected) const {
        std::uintptr_t table=0,col=0;unsigned fields[6]{};char name[96]{};
        return read_at(object,table) && read_at(table-8,col) && read_at(col,fields) && fields[0]==1 && col-fields[5]==module &&
            read(reinterpret_cast<void*>(module+fields[3]+16),name,sizeof(name)) && (name[95]=0,std::strcmp(name,expected)==0);
    }
    std::uintptr_t human(const Binding& b) const {
        if(!binding_valid(b))return 0;
        std::uint64_t packed=0;unsigned count=0;if(!read_at(b.entity+0x78,packed))return 0;
        if(packed>>56)count=unsigned(packed>>56)-1;else if(!read_at(b.entity+0x80,count))return 0;
        if(!count || count>128)return 0;
        const auto arena=b.entity-((b.entity_handle<<4)&0xffffffffull);
        for(unsigned i=0;i<count;++i){
            std::uint64_t handle=0,found=0;std::uintptr_t table=0,owner=0,value=0;
            if(!read_at((packed&0xffffffffffffull)+i*8,handle))return 0;
            const auto component=arena+((handle<<4)&0xffffffffull);
            if(!read_at(component,table) || table!=game+0x281f270)continue;
            if(read_at(component+8,found) && found==handle && occupied(component,handle) && read_at(component+0x10,owner) && owner==b.entity &&
               read_at(component+0x78,value) && read_at(value,table) && table==game+0x293ba38)return value;
        }
        return 0;
    }
    unsigned regions(const Binding& b,Region* out) const {
        const auto ai=human(b);std::uintptr_t module=0;
        if(!ai || !matrix || !bounds || !read_at(ai+0x628,module) || !type(module,game,".?AVHumanWeaponModule@@"))return 0;
        unsigned used=0;
        for(unsigned slot:{0x28u,0x48u,0x68u}){
            std::uintptr_t vis=0,model=0,proxy=0,entity=0,parent=0,owner=0,state=0,pose=0;std::uint64_t handle=0;unsigned short visible=0,bones=0;
            if(!read_at(module+slot,vis) || !type(vis,game,".?AVWeaponVis@@") || !read_at(vis+8,model) ||
               !read_at(model,owner) || owner!=engine+0x1915218 || !read_at(model+0x35c,visible) || !(visible&15) ||
               !read_at(vis+0x128,owner) || owner!=module-8 || !read_at(vis+0x38,proxy) ||
               !read_at(proxy+0x10,entity) || !read_at(entity+8,handle) || !occupied(entity,handle) ||
               !read_at(entity+0x10,parent) || !(parent==b.entity || (read_at(b.entity+0x10,owner) && owner==parent && read_at(parent+8,handle) && occupied(parent,handle))) || !read_at(model+0x418,state) || !state ||
               !read_at(state+0x20,pose) || !pose || !read_at(state+0x28,bones) || bones>1023)continue;
            bool pose_valid=true;
            for(unsigned state_offset:{0x418u,0x428u}){
                std::uintptr_t animation=0,matrices=0;unsigned short count=0;
                pose_valid=pose_valid && read_at(model+state_offset,state) && state && read_at(state+0x20,animation) && animation &&
                    read_at(state+0x28,count) && count>0 && count<=1023 && read_at(animation+0x78,matrices) && matrices;
                float first[12]{};pose_valid=pose_valid && read(reinterpret_cast<void*>(matrices),first,sizeof(first));
            }
            if(!pose_valid)continue;
            float world[12]{},box[6]{};
            if(!read(matrix(reinterpret_cast<void*>(model),0),world,48) || !read(bounds(reinterpret_cast<void*>(model)),box,24))continue;
            bool valid=true;for(float f:world)valid=valid && std::isfinite(f);for(float f:box)valid=valid && std::isfinite(f);
            float body[12]{};valid=valid && read(reinterpret_cast<void*>(b.xform+0x80),body,48);
            if(!valid || length(Vec{world[3]-body[3],world[7]-body[7],world[11]-body[11]})>3)continue;
            unsigned axis=0;double span[3]{};Vec centre{(box[0]+box[3])*.5,(box[1]+box[4])*.5,(box[2]+box[5])*.5};
            for(unsigned i=0;i<3;++i){span[i]=box[i+3]-box[i];if(span[i]>span[axis])axis=i;}
            if(span[axis]<.12 || span[axis]>3)continue;
            const double half=span[axis]*.5;const Vec extent{axis==0?half:0,axis==1?half:0,axis==2?half:0};
            const Vec a=centre-extent,c=centre+extent;
            const double radius=std::clamp(std::max(span[(axis+1)%3],span[(axis+2)%3])*.5,.025,.20);
            out[used++]={transform(world,a),transform(world,c),radius};if(used==2)break;
        }
        return used;
    }
};
NativeEnemyWeapons enemy_weapons;
