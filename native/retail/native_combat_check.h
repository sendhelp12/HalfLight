// One-shot offline lab check. No keys, camera writes or guest pose overrides.
// The same detector and dispatch path are used by play and by this check.
struct CombatCheck {std::uint32_t magic,pid;std::uint64_t session,sequence,expiry,entity;unsigned bank,kind;};
static_assert(sizeof(CombatCheck)==48);
CombatCheck pending_check{};std::uint64_t check_sequence=0;
struct CombatResult {std::uint64_t sequence;unsigned status;float before,after;};
CombatResult check_result{};
std::atomic<float> last_contact_speed{0},last_contact_scale{0},last_contact_coefficient{0};
std::atomic<unsigned> last_enemy_weapon_regions{0},last_contact_region{0};
void prepare_melee_damage(unsigned char* damage,unsigned category){
    std::memset(damage+0x20,0,4);damage[0xd0]=static_cast<unsigned char>(category);
    // The captured native blade profile feeds DamageableBody's wound/cut tests.
    // Punch seeds carry zeros here; never apply cutting traits to thrusts/blunts.
    // shortcut: cutting families share this captured blade profile; calibrate per weapon if native wound rates differ.
    const float body_profile[4]={category==1?.7f:0.f,0.f,category==1?.5f:0.f,category==1?.5f:0.f};
    std::memcpy(damage+0x5c,body_profile,sizeof(body_profile));
}
bool dispatch_contact(TargetState& target,unsigned index,const Contact& contact,std::uint64_t tick){
    if(!contact.hit || !living_target(target,tick) || !seed_owner_valid())return false;
    const auto& profile=impact_profiles[index];
    auto response=impact(contact,profile,contact.edge,target.balance,target.last_dispatch?double(tick-target.last_dispatch)/1000:0);
    if(contact.region>=12){response.scale=0;response.stick=0;response.category=72;response.type=4;response.severity=1;response.move=1;response.interrupt=true;response.knockdown=false;}
    last_contact_region.store(contact.region);last_contact_speed.store(float(contact.speed));last_contact_scale.store(response.scale);
    alignas(16) unsigned char damage[0xe0]{};copy_damage(damage,seed);prepare_melee_damage(damage,response.category);
    std::uintptr_t owner=0,seed_owner=0,container=0,seed_container=0,container_table=0;
    std::memcpy(&owner,damage+0x70,8);std::memcpy(&seed_owner,seed+0x70,8);
    if(owner==seed_owner || !read_at(owner,container) || !read_at(seed_owner,seed_container) || container==seed_container ||
       !read_at(container,container_table) || container_table!=game+0x2709118){destroy_damage(damage);return false;}
    using Evaluate=const void*(*)(void*);
    const auto base=reinterpret_cast<Evaluate>(game+0xa81d30)(reinterpret_cast<void*>(container));
    float baseline=0;unsigned source_channel=13;
    if(reinterpret_cast<std::uintptr_t>(base)!=container+0x3a8){destroy_damage(damage);return false;}
    for(unsigned channel:{0u,1u,2u,13u}){
        float value=0;
        if(!read_at(container+0x3a8+12+channel*16,value) || !std::isfinite(value) || value<0 || value>1000000){destroy_damage(damage);return false;}
        if(value>baseline){baseline=value;source_channel=channel;}
    }
    const unsigned destination=response.category==18?1u:2u;
    const auto factor_offset=12+destination*16;
    if(baseline<=0 || !scale_owned_melee(container,1,source_channel,destination)){
        destroy_damage(damage);return false;
    }
    const auto frozen=reinterpret_cast<Evaluate>(game+0xa81d30)(reinterpret_cast<void*>(container));
    float frozen_health=0;
    if(reinterpret_cast<std::uintptr_t>(frozen)!=container+0x3a8 || !read_at(container+0x3a8+factor_offset,frozen_health) ||
       !std::isfinite(frozen_health) || frozen_health<=0 || !scale_owned_melee(container,response.scale*baseline/frozen_health,destination,destination)){
        destroy_damage(damage);return false;
    }
    const auto evaluated=reinterpret_cast<Evaluate>(game+0xa81d30)(reinterpret_cast<void*>(container));
    float health_damage[3]{};
    if(reinterpret_cast<std::uintptr_t>(evaluated)!=container+0x3a8 || !read(static_cast<const unsigned char*>(evaluated)+factor_offset,health_damage,12)){
        destroy_damage(damage);return false;
    }
    for(float value:health_damage)if(!std::isfinite(value) || value<0 || value>1000000){destroy_damage(damage);return false;}
    last_contact_coefficient.store(health_damage[0]);
    damage[0x20]=static_cast<unsigned char>(response.type);damage[0x21]=3;
    damage[0x22]=static_cast<unsigned char>(response.severity);damage[0x23]=static_cast<unsigned char>(response.move);
    damage[0x24]=static_cast<unsigned char>((response.interrupt?1:0)|(response.knockdown?4:0));
    std::uint32_t flags=0; // Native reaction byte requests falling; RAGDOLL damage bypasses normal health.
    std::memcpy(damage+0xd4,&flags,4);
    std::memcpy(damage+0xd8,&response.force,4);
    // The captured setup hit's bone belongs to that old contact. Native
    // PrepareDamageInfo maps this target's skeleton index to its body region.
    int bone=-1;auto& rig=target_rigs[&target-targets];
    constexpr unsigned hit_bones[12]={0,1,3,5,6,8,9,11,12,14,15,3};
    if(rig.ready && contact.region<12)bone=rig.index[hit_bones[contact.region]];
    std::memcpy(damage+0x4c,&bone,4);
    const float position[3]={float(contact.point.x),float(contact.point.y),float(contact.point.z)};
    const float normal[3]={float(contact.normal.x),float(contact.normal.y),float(contact.normal.z)};
    const float direction[3]={float(contact.direction.x),float(contact.direction.y),float(contact.direction.z)};
    std::memcpy(damage+0x28,position,12);std::memcpy(damage+0x34,normal,12);std::memcpy(damage+0x40,direction,12);
    if(!input_armed.load() && response.category==1)capture_damage_probe(damage,bridge_probe,bridge_probe_ready);
    const std::uintptr_t message[3]={message_header[0],message_header[1],reinterpret_cast<std::uintptr_t>(damage)};
    target.last_weapon=index;target.last_dispatch=tick;record_health(target,tick,2,target.health,target.health);
    take_damage(reinterpret_cast<void*>(target.binding.receiver),message);damage_calls.fetch_add(1);
    // Diagnostics measure native damage only, never alter source physics.
    if(input_armed.load())record_impact(target,index,contact,response,tick);
    destroy_damage(damage);living_target(target,tick);return true;
}
void run_combat_check(std::uint64_t tick){
    const auto request=pending_check;
    if(!request.sequence || request.sequence<=check_sequence)return;
    check_sequence=request.sequence;check_result={request.sequence,1,0,0};
    if(input_armed.load() || request.expiry<=tick || request.expiry>tick+30000 ||
       request.bank>=(dual?bank_count:1u) || request.kind>8)return;
    for(auto& target:targets){
        if(!target.present || target.binding.entity_handle!=request.entity)continue;
        float value=0;if(!native_health.read_health(target.binding,value)){check_result.status=2;return;}
        check_result.before=value;check_result.after=value;
        if(value<=0){check_result.status=3;return;}
        if(!request.kind){Region weapons[2]{};last_enemy_weapon_regions.store(enemy_weapons.regions(target.binding,weapons));check_result.status=0;return;}
        float body[12]{};if(!read(reinterpret_cast<void*>(target.binding.xform+0x80),body,48))return;
        Region regions[16]{};auto& rig=target_rigs[&target-targets];
        const auto count=rig.regions(target.binding.xform,body,regions);
        if(count!=12){check_result.status=4;return;}
        const auto& region=regions[request.kind==5?11:request.kind==6?7:1];const auto centre=(region.a+region.b)*.5;
        const auto& edge=dual?weapon_banks[request.bank].contact:weapon_contact;
        const Vec edge_a{edge.a[0],edge.a[1],edge.a[2]},edge_b{edge.b[0],edge.b[1],edge.b[2]},mid=(edge_a+edge_b)*.5;
        const Vec miss=request.kind==1?Vec{0,5,0}:Vec{0,0,0};
        const double travel=request.kind==3?.055:request.kind==4?.3:.8;
        const Vec sweep=request.kind==7?unit(edge_b-edge_a)*travel:Vec{travel,0,0};
        const Vec start=centre+miss-sweep-mid,end=centre+miss+sweep-mid;
        for(unsigned i=0;i<count;++i)regions[i].radius+=edge.radius;
        Detector detector;detector.sample_regions(edge_a+start,edge_b+start,regions,count,tick/1000.0-.15,true);
        auto contact=detector.sample_regions(edge_a+end,edge_b+end,regions,count,tick/1000.0,true);
        if(request.kind==1){check_result.status=contact.hit?5:0;return;}
        if(request.kind==8)contact.region=12;
        if(!dispatch_contact(target,request.bank,contact,tick)){check_result.status=6;return;}
        if(native_health.read_health(target.binding,value))check_result.after=value;
        check_result.status=0;return;
    }
    check_result.status=7;
}
