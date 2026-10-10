#pragma once
bool hash_matches(HMODULE module,const unsigned char* expected) {
    wchar_t path[32768]{};
    if(!GetModuleFileNameW(module,path,32768))return false;
    HANDLE file=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(file==INVALID_HANDLE_VALUE)return false;
    HCRYPTPROV provider=0;HCRYPTHASH hash=0;
    bool ok=CryptAcquireContextW(&provider,nullptr,nullptr,PROV_RSA_AES,CRYPT_VERIFYCONTEXT)!=0;
    if(ok)ok=CryptCreateHash(provider,CALG_SHA_256,0,0,&hash)!=0;
    unsigned char buffer[65536]{};DWORD bytes=0;
    while(ok) {
        if(!ReadFile(file,buffer,sizeof(buffer),&bytes,nullptr)){ok=false;break;}
        if(!bytes)break;
        if(!CryptHashData(hash,buffer,bytes,0)){ok=false;break;}
    }
    unsigned char actual[32]{};DWORD size=sizeof(actual);
    if(ok)ok=CryptGetHashParam(hash,HP_HASHVAL,actual,&size,0)!=0 && size==32;
    if(ok)for(unsigned i=0;i<32;++i)if(actual[i]!=expected[i])ok=false;
    if(hash)CryptDestroyHash(hash);if(provider)CryptReleaseContext(provider,0);CloseHandle(file);
    return ok;
}


