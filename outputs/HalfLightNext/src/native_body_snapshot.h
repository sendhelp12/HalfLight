#pragma once
// Written by the native update phase; the file worker never reads game bones.
struct BodyShape {std::uint64_t entity,root;std::uint32_t region,reserved;float centre[3],axis[3],radius,half;};
struct BodySnapshot {
    std::uint32_t magic,pid;std::uint64_t session,sequence,expiry;
    std::uint32_t count,reserved;BodyShape shapes[224];
};
static_assert(sizeof(BodyShape)==56 && sizeof(BodySnapshot)==12584);
std::atomic_flag body_snapshot_lock=ATOMIC_FLAG_INIT;
BodySnapshot body_snapshot{};
std::uint64_t body_sequence=0;
void publish_bodies(const BodySnapshot& snapshot){
    if(body_snapshot_lock.test_and_set(std::memory_order_acquire))return;
    body_snapshot=snapshot;body_snapshot_lock.clear(std::memory_order_release);
}
bool write_bodies(const wchar_t* path,const wchar_t* temporary){
    if(body_snapshot_lock.test_and_set(std::memory_order_acquire))return false;
    const auto snapshot=body_snapshot;body_snapshot_lock.clear(std::memory_order_release);
    HANDLE file=CreateFileW(temporary,GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_DELETE,nullptr,CREATE_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(file==INVALID_HANDLE_VALUE)return false;
    DWORD bytes=0;const bool good=WriteFile(file,&snapshot,sizeof(snapshot),&bytes,nullptr) && bytes==sizeof(snapshot);
    CloseHandle(file);return good && MoveFileExW(temporary,path,MOVEFILE_REPLACE_EXISTING);
}
