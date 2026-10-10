#pragma once
struct ImpactEvent {std::uint64_t sequence,expiry,entity;unsigned bank,region;float point[3],normal[3],force,stick;};
struct ImpactSnapshot {std::uint32_t magic,pid;std::uint64_t session;ImpactEvent events[64];};
static_assert(sizeof(ImpactEvent)==64 && sizeof(ImpactSnapshot)==4112);
ImpactSnapshot impact_snapshot{};std::uint64_t impact_sequence=0;
void record_impact(const TargetState& target,unsigned bank,const Contact& c,const Impact& response,std::uint64_t tick){
    auto& e=impact_snapshot.events[++impact_sequence%64];
    e={impact_sequence,tick+500,target.binding.entity_handle,bank,c.region,{float(c.point.x),float(c.point.y),float(c.point.z)},
        {float(c.normal.x),float(c.normal.y),float(c.normal.z)},response.force,response.stick};
}
