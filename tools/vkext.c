#include <windows.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
typedef struct { int sType; const void *pNext; const char *app; uint32_t appVer; const char *eng; uint32_t engVer; uint32_t apiVer; } AppInfo;
typedef struct { int sType; const void *pNext; uint32_t flags; const AppInfo *pApp; uint32_t layerCount; const char *const *layers; uint32_t extCount; const char *const *exts; } InstCI;
typedef struct { char name[256]; uint32_t spec; } ExtProps;
int main(void){
    HMODULE vk=LoadLibraryA("vulkan-1.dll"); if(!vk){printf("no vulkan\n");return 1;}
    void *(*gipa)(void*,const char*)=(void*(*)(void*,const char*))GetProcAddress(vk,"vkGetInstanceProcAddr");
    int (*create)(const InstCI*,const void*,void**)=(int(*)(const InstCI*,const void*,void**))GetProcAddress(vk,"vkCreateInstance");
    AppInfo ai={0,0,"vkext",1,"vkext",1,0x00403000u}; InstCI ci={1,0,0,&ai,0,0,0,0};
    void *inst=0; int vr=create(&ci,0,&inst); printf("create vr=%d inst=%p\n",vr,inst); if(vr)return 1;
    int (*epd)(void*,uint32_t*,void**)=(int(*)(void*,uint32_t*,void**))gipa(inst,"vkEnumeratePhysicalDevices");
    int (*edep)(void*,const char*,uint32_t*,ExtProps*)=(int(*)(void*,const char*,uint32_t*,ExtProps*))gipa(inst,"vkEnumerateDeviceExtensionProperties");
    uint32_t n=0; epd(inst,&n,0); void *d[4]; if(n>4)n=4; epd(inst,&n,d);
    printf("devices=%u\n",n);
    for(uint32_t i=0;i<n;i++){ uint32_t c=0; edep(d[i],0,&c,0); ExtProps *p=malloc(c*sizeof(*p)); edep(d[i],0,&c,p);
        printf("dev %u exts=%u\n",i,c);
        for(uint32_t j=0;j<c;j++) if(strstr(p[j].name,"video")) printf("  %s\n",p[j].name);
        free(p);} return 0;
}
