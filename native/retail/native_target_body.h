#pragma once
// Included after the verified native arm getter has been declared.
struct TargetRig {
    std::uintptr_t definition=0;unsigned count=0;int index[16]{};bool ready=false;
    bool prepare(std::uintptr_t skeleton){
        std::uintptr_t current=0,storage=0,elements=0;unsigned current_count=0;
        if(!read_at(skeleton+0x2b0,current) || !read_at(skeleton+0x2a8,current_count))return false;
        if(ready && current==definition && current_count==count)return true;
        ready=false;definition=current;count=current_count;
        for(auto& i:index)i=-1;
        if(!definition || count<16 || count>1024 || !read_at(definition+0x78,storage) || !read_at(storage+8,elements))return false;
        constexpr const char* names[16]={"pelvis","spine3","neck","head","r_upperarm","r_forearm","r_hand","l_upperarm","l_forearm","l_hand","r_thigh","r_calf","r_foot","l_thigh","l_calf","l_foot"};
        for(unsigned i=0;i<count;++i){
            std::uintptr_t tagged=0;char name[64]{};
            if(!read_at(elements+i*0xd0+0x78,tagged) || !read(reinterpret_cast<void*>(tagged&0x1fffffffffffffffull),name,sizeof(name)))continue;
            name[63]=0;
            for(unsigned j=0;j<16;++j)if(!std::strcmp(name,names[j])){if(index[j]!=-1)return false;index[j]=int(i);}
        }
        for(int i:index)if(i<0)return false;
        ready=true;return true;
    }
    unsigned regions(std::uintptr_t skeleton,const float* world,Region* out){
        if(!arm.get_model || !prepare(skeleton))return 0;
        Vec points[16]{};
        for(unsigned i=0;i<16;++i){
            float model[12]{};
            if(!read(arm.get_model(reinterpret_cast<void*>(skeleton),index[i]),model,sizeof(model)))return 0;
            for(float f:model)if(!std::isfinite(f))return 0;
            points[i]=transform(world,{model[3],model[7],model[11]});
            if(length(points[i]-Vec{world[3],world[7],world[11]})>4)return 0;
        }
        const Vec up{world[1],world[5],world[9]};const double scale=length(up);
        if(scale<.5 || scale>2)return 0;
        // Approximate flesh thickness follows actual named, animated bones.
        constexpr unsigned links[11][2]={{0,1},{1,2},{2,3},{4,5},{5,6},{7,8},{8,9},{10,11},{11,12},{13,14},{14,15}};
        constexpr double radii[11]={.22,.21,.12,.105,.085,.105,.085,.13,.10,.13,.10};
        for(unsigned i=0;i<11;++i)out[i]={points[links[i][0]],points[links[i][1]],radii[i]*scale};
        out[11]={points[3],points[3]+up*.08,.14*scale};return 12;
    }
};
TargetRig target_rigs[max_targets]{};
