#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/memfd.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/inotify.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/syscall.h>
#include <unistd.h>

#define MAX_HASHED_FILE (32U << 20)
#define MAX_LAUNCHER_SOURCE (1U << 20)
#define ALL_SEALS (F_SEAL_SEAL | F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_WRITE)
#define WATCH_MASK (IN_MODIFY | IN_ATTRIB | IN_CLOSE_WRITE | IN_MOVE_SELF | IN_DELETE_SELF)

static const char *PYTHON_PATH = "/usr/bin/python3.12";
static const char *PYTHON_SHA256 = "c2c20b4745d447551221ec3d4e70f92c270c4609fe3df34fc52ea6dd46e92273";
static const char *ARGPARSE_PATH = "/usr/lib/python3.12/argparse.py";
static const char *ARGPARSE_SHA256 = "29395feb61bc376ca4ff9d44069af8d914ec2a1f25a4bd7978f6e2afef5bc07f";
static const char *PYCACHE_PREFIX = "/tmp/planora-puproj-frontier-joint-v12-bootstrap-pycache";

/* This loader is compiled into the static ELF trust root.  Launcher source is
 * data until this code has replayed its sealed descriptor and source binding. */
static const char *LOADER =
"import fcntl,hashlib,json,os,stat,sys\n"
"fd=int(sys.argv[1]); expected=sys.argv[2]; path=sys.argv[3]; watch=int(sys.argv[4]); manifest_fd=int(sys.argv[14]); manifest_expected=sys.argv[15]; manifest_path=sys.argv[16]; forwarded=sys.argv[26:]\n"
"required=fcntl.F_SEAL_SEAL|fcntl.F_SEAL_SHRINK|fcntl.F_SEAL_GROW|fcntl.F_SEAL_WRITE\n"
"ident=lambda r:(int(r.st_dev),int(r.st_ino),int(r.st_size),stat.S_IFMT(r.st_mode),stat.S_IMODE(r.st_mode),int(r.st_uid),int(r.st_nlink),int(r.st_mtime_ns),int(r.st_ctime_ns))\n"
"claimed=tuple(int(v) for v in sys.argv[5:14])\n"
"before=os.fstat(fd); seals=int(fcntl.fcntl(fd,fcntl.F_GET_SEALS)); parts=[]; off=0\n"
"while off<before.st_size:\n"
" b=os.pread(fd,min(1<<20,before.st_size-off),off)\n"
" if not b: raise RuntimeError('sealed launcher ended early')\n"
" parts.append(b); off+=len(b)\n"
"source=b''.join(parts); after=os.fstat(fd)\n"
"try: events=os.read(watch,65536)\n"
"except BlockingIOError: events=b''\n"
"named=os.lstat(path)\n"
"if ident(before)[:7]!=ident(after)[:7] or seals&required!=required or hashlib.sha256(source).hexdigest()!=expected or ident(named)!=claimed or events: raise RuntimeError('pre-exec launcher mutation/seal/hash contract rejected')\n"
"binding={'path':path,'sha256':expected,'fd':fd,'device':int(after.st_dev),'inode':int(after.st_ino),'size':int(after.st_size),'file_type':stat.S_IFMT(after.st_mode),'mode':stat.S_IMODE(after.st_mode),'uid':int(after.st_uid),'nlink':int(after.st_nlink),'seals':seals,'required_seals':required,'source_identity':list(claimed),'source_watch_fd':watch,'transport':'native_bootstrap_sealed_memfd_before_launcher_execution','bootstrap_sha256':os.environ['PUPROJ_V12_BOOTSTRAP_SHA256']}\n"
"mb=os.fstat(manifest_fd); ms=int(fcntl.fcntl(manifest_fd,fcntl.F_GET_SEALS)); mp=[]; mo=0\n"
"while mo<mb.st_size:\n"
" b=os.pread(manifest_fd,min(1<<20,mb.st_size-mo),mo)\n"
" if not b: raise RuntimeError('sealed freeze manifest ended early')\n"
" mp.append(b); mo+=len(b)\n"
"manifest_raw=b''.join(mp); manifest_claimed=tuple(int(v) for v in sys.argv[17:26]); manifest_named=os.lstat(manifest_path)\n"
"if ms&required!=required or hashlib.sha256(manifest_raw).hexdigest()!=manifest_expected or ident(manifest_named)!=manifest_claimed: raise RuntimeError('pre-exec freeze manifest seal/hash contract rejected')\n"
"manifest_binding={'path':manifest_path,'sha256':manifest_expected,'fd':manifest_fd,'device':int(mb.st_dev),'inode':int(mb.st_ino),'size':int(mb.st_size),'seals':ms,'required_seals':required,'source_identity':list(manifest_claimed),'transport':'native_bootstrap_sealed_memfd_before_target_execution'}\n"
"filename=f'<sealed-puproj-frontier-v12-launcher:{expected}>'; sys.argv=[filename,*forwarded]\n"
"scope={'__name__':'__main__','__file__':filename,'__package__':None,'__cached__':None,'__captured_launcher_sha256__':expected,'__bootstrap_loader_protocol__':'planora.native-sealed-python-bootstrap.v1','__bootstrap_launcher_binding__':binding,'__bootstrap_manifest_binding__':manifest_binding,'__bootstrap_runtime_binding__':{'python_sha256':os.environ['PUPROJ_V12_PYTHON_SHA256'],'bootstrap_sha256':os.environ['PUPROJ_V12_BOOTSTRAP_SHA256'],'isolated':True,'no_site':True,'dont_write_bytecode':True,'pycache_prefix':sys.pycache_prefix},'__bootstrap_launcher_fd__':fd}\n"
"exec(compile(source,filename,'exec',dont_inherit=True),scope)\n";

typedef struct { uint32_t h[8]; uint64_t bits; unsigned char buf[64]; size_t used; } sha256_ctx;
static const uint32_t K[64] = {
  0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
  0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
  0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
  0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
  0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
};
static uint32_t rr(uint32_t x, unsigned n){ return (x>>n)|(x<<(32-n)); }
static void sha_block(sha256_ctx *c,const unsigned char *p){
  uint32_t w[64],a,b,d,e,f,g,h,t1,t2,cc;
  for(int i=0;i<16;i++) w[i]=((uint32_t)p[i*4]<<24)|((uint32_t)p[i*4+1]<<16)|((uint32_t)p[i*4+2]<<8)|p[i*4+3];
  for(int i=16;i<64;i++){ uint32_t x=w[i-15],y=w[i-2]; w[i]=w[i-16]+(rr(x,7)^rr(x,18)^(x>>3))+w[i-7]+(rr(y,17)^rr(y,19)^(y>>10)); }
  a=c->h[0];b=c->h[1];cc=c->h[2];d=c->h[3];e=c->h[4];f=c->h[5];g=c->h[6];h=c->h[7];
  for(int i=0;i<64;i++){ t1=h+(rr(e,6)^rr(e,11)^rr(e,25))+((e&f)^((~e)&g))+K[i]+w[i]; t2=(rr(a,2)^rr(a,13)^rr(a,22))+((a&b)^(a&cc)^(b&cc)); h=g;g=f;f=e;e=d+t1;d=cc;cc=b;b=a;a=t1+t2; }
  c->h[0]+=a;c->h[1]+=b;c->h[2]+=cc;c->h[3]+=d;c->h[4]+=e;c->h[5]+=f;c->h[6]+=g;c->h[7]+=h;
}
static void sha_init(sha256_ctx *c){ uint32_t q[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19}; memcpy(c->h,q,sizeof(q));c->bits=0;c->used=0; }
static void sha_update(sha256_ctx *c,const unsigned char *p,size_t n){ c->bits+=(uint64_t)n*8; while(n){ size_t z=64-c->used;if(z>n)z=n;memcpy(c->buf+c->used,p,z);c->used+=z;p+=z;n-=z;if(c->used==64){sha_block(c,c->buf);c->used=0;} } }
static void sha_final(sha256_ctx *c,unsigned char out[32]){ size_t u=c->used;c->buf[u++]=0x80;if(u>56){memset(c->buf+u,0,64-u);sha_block(c,c->buf);u=0;}memset(c->buf+u,0,56-u);for(int i=0;i<8;i++)c->buf[63-i]=(unsigned char)(c->bits>>(i*8));sha_block(c,c->buf);for(int i=0;i<8;i++){out[i*4]=(unsigned char)(c->h[i]>>24);out[i*4+1]=(unsigned char)(c->h[i]>>16);out[i*4+2]=(unsigned char)(c->h[i]>>8);out[i*4+3]=(unsigned char)c->h[i];} }
static void hex32(const unsigned char in[32],char out[65]){ static const char x[]="0123456789abcdef";for(int i=0;i<32;i++){out[i*2]=x[in[i]>>4];out[i*2+1]=x[in[i]&15];}out[64]=0; }

static int hash_fd(int fd,char out[65],unsigned char **copy,size_t *copy_n){
  struct stat st;if(fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_size<0||(uint64_t)st.st_size>MAX_HASHED_FILE){return -1;}
  size_t n=(size_t)st.st_size;unsigned char *p=malloc(n?n:1);if(!p)return -1;size_t off=0;while(off<n){ssize_t r=pread(fd,p+off,n-off,(off_t)off);if(r<=0){free(p);return -1;}off+=(size_t)r;}
  struct stat end;if(fstat(fd,&end)||st.st_dev!=end.st_dev||st.st_ino!=end.st_ino||st.st_size!=end.st_size||st.st_mtim.tv_sec!=end.st_mtim.tv_sec||st.st_mtim.tv_nsec!=end.st_mtim.tv_nsec||st.st_ctim.tv_sec!=end.st_ctim.tv_sec||st.st_ctim.tv_nsec!=end.st_ctim.tv_nsec){free(p);return -1;}
  sha256_ctx c;unsigned char d[32];sha_init(&c);sha_update(&c,p,n);sha_final(&c,d);hex32(d,out);if(copy){*copy=p;*copy_n=n;}else free(p);return 0;
}
static void die(const char *m){ fprintf(stderr,"PU-PROJ v12 native bootstrap: %s\n",m);exit(70); }
static int valid_hex(const char *s){ if(!s||strlen(s)!=64)return 0;for(int i=0;i<64;i++)if(!((s[i]>='0'&&s[i]<='9')||(s[i]>='a'&&s[i]<='f')))return 0;return 1; }
static int memfd_new(const char *name){ return (int)syscall(SYS_memfd_create,name,MFD_ALLOW_SEALING); }
static void verify_immutable_system_file(const char *path,const char *expected){
  struct stat st;struct statvfs fs;char got[65];int fd=open(path,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
  if(fd<0||fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_uid!=65534||(st.st_mode&0022)||statvfs(path,&fs)||!(fs.f_flag&ST_RDONLY)||hash_fd(fd,got,NULL,NULL)||strcmp(got,expected))die("immutable pinned system file rejected");
  close(fd);
  const char *parents[]={"/","/usr","/usr/bin","/usr/lib","/usr/lib/python3.12",NULL};
  for(int i=0;parents[i];i++)if(lstat(parents[i],&st)||!S_ISDIR(st.st_mode)||st.st_uid!=65534||(st.st_mode&0022))die("immutable system ancestor chain rejected");
}

int main(int argc,char **argv){
  const char *self_expected=NULL,*launcher_expected=NULL,*launcher=NULL,*manifest_path=NULL,*manifest_expected=NULL,*mode=NULL;int mutate=0,capture_test=0;
  for(int i=1;i<argc;i++){
    if(!strcmp(argv[i],"--expected-bootstrap-sha256")&&i+1<argc)self_expected=argv[++i];
    else if(!strcmp(argv[i],"--expected-launcher-sha256")&&i+1<argc)launcher_expected=argv[++i];
    else if(!strcmp(argv[i],"--launcher-path")&&i+1<argc)launcher=argv[++i];
    else if(!strcmp(argv[i],"--manifest-path")&&i+1<argc)manifest_path=argv[++i];
    else if(!strcmp(argv[i],"--expected-manifest-sha256")&&i+1<argc)manifest_expected=argv[++i];
    else if(!strcmp(argv[i],"--mutate-restore-test"))mutate=1;
    else if(!strcmp(argv[i],"--capture-test")){capture_test=1;mode="--capture-test";}
    else if(!strcmp(argv[i],"--self-test")||!strcmp(argv[i],"--dry-run")||!strcmp(argv[i],"--sealed-import-probe")||!strcmp(argv[i],"--launch"))mode=argv[i];
    else die("argument contract rejected");
  }
  if(!valid_hex(self_expected)||!valid_hex(launcher_expected)||!launcher||!mode)die("independent SHA-256 pins, exact target path, and mode required");
  if(!capture_test&&(!valid_hex(manifest_expected)||!manifest_path))die("exact freeze manifest path and independent pin required");
  int self=open("/proc/self/exe",O_RDONLY|O_CLOEXEC);char digest[65];if(self<0||hash_fd(self,digest,NULL,NULL)||strcmp(digest,self_expected))die("/proc/self/exe replay differs from independent bootstrap pin");close(self);
  int watch=inotify_init1(IN_NONBLOCK);if(watch<0||inotify_add_watch(watch,launcher,WATCH_MASK)<0)die("launcher mutation watch failed");
  int src=open(launcher,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);struct stat before,named;if(src<0||fstat(src,&before)||!S_ISREG(before.st_mode)||before.st_nlink!=1||before.st_size<0||(uint64_t)before.st_size>MAX_LAUNCHER_SOURCE)die("launcher source contract rejected");
  unsigned char *raw=NULL;size_t raw_n=0;if(hash_fd(src,digest,&raw,&raw_n)||strcmp(digest,launcher_expected))die("launcher stable-read SHA-256 drift");
  if(lstat(launcher,&named)||before.st_dev!=named.st_dev||before.st_ino!=named.st_ino||before.st_size!=named.st_size)die("launcher named identity drift");
  int sealed=memfd_new("planora-puproj-v12-launcher");if(sealed<0||write(sealed,raw,raw_n)!=(ssize_t)raw_n||fchmod(sealed,0400)||fcntl(sealed,F_ADD_SEALS,ALL_SEALS))die("launcher memfd sealing failed");
  if((fcntl(sealed,F_GET_SEALS)&ALL_SEALS)!=ALL_SEALS)die("launcher seal replay failed");
  if(mutate){ int w=open(launcher,O_WRONLY|O_TRUNC);if(w<0||write(w,"attacker\n",9)!=9||fsync(w)||close(w))die("capture-test mutation setup failed");w=open(launcher,O_WRONLY|O_TRUNC);if(w<0||write(w,raw,raw_n)!=(ssize_t)raw_n||fsync(w)||close(w))die("capture-test restore setup failed"); }
  unsigned char events[4096];ssize_t event_n=read(watch,events,sizeof(events));struct stat final_named;if(fstat(src,&named)||lstat(launcher,&final_named))die("launcher final identity replay failed");
  int clock_drift=before.st_mtim.tv_sec!=named.st_mtim.tv_sec||before.st_mtim.tv_nsec!=named.st_mtim.tv_nsec||before.st_ctim.tv_sec!=named.st_ctim.tv_sec||before.st_ctim.tv_nsec!=named.st_ctim.tv_nsec||before.st_mtim.tv_sec!=final_named.st_mtim.tv_sec||before.st_mtim.tv_nsec!=final_named.st_mtim.tv_nsec||before.st_ctim.tv_sec!=final_named.st_ctim.tv_sec||before.st_ctim.tv_nsec!=final_named.st_ctim.tv_nsec;
  if(event_n>0||clock_drift){ free(raw);close(src);close(sealed);close(watch);fprintf(stderr,"MUTATE_RESTORE_REJECTED\n");return 73; }
  if(capture_test){ free(raw);close(src);close(sealed);close(watch);puts("CAPTURE_TEST_PASS");return 0; }
  int manifest_src=open(manifest_path,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);struct stat manifest_before,manifest_named;if(manifest_src<0||fstat(manifest_src,&manifest_before)||!S_ISREG(manifest_before.st_mode)||manifest_before.st_nlink!=1||manifest_before.st_size<0||(uint64_t)manifest_before.st_size>MAX_LAUNCHER_SOURCE)die("freeze manifest source contract rejected");
  unsigned char *manifest_raw=NULL;size_t manifest_n=0;if(hash_fd(manifest_src,digest,&manifest_raw,&manifest_n)||strcmp(digest,manifest_expected)||lstat(manifest_path,&manifest_named)||manifest_before.st_dev!=manifest_named.st_dev||manifest_before.st_ino!=manifest_named.st_ino||manifest_before.st_size!=manifest_named.st_size||manifest_before.st_mtim.tv_sec!=manifest_named.st_mtim.tv_sec||manifest_before.st_mtim.tv_nsec!=manifest_named.st_mtim.tv_nsec||manifest_before.st_ctim.tv_sec!=manifest_named.st_ctim.tv_sec||manifest_before.st_ctim.tv_nsec!=manifest_named.st_ctim.tv_nsec)die("freeze manifest stable-read SHA-256/identity drift");
  int manifest_sealed=memfd_new("planora-freeze-manifest");if(manifest_sealed<0||write(manifest_sealed,manifest_raw,manifest_n)!=(ssize_t)manifest_n||fchmod(manifest_sealed,0400)||fcntl(manifest_sealed,F_ADD_SEALS,ALL_SEALS)||(fcntl(manifest_sealed,F_GET_SEALS)&ALL_SEALS)!=ALL_SEALS)die("freeze manifest memfd sealing failed");
  verify_immutable_system_file(ARGPARSE_PATH,ARGPARSE_SHA256);
  verify_immutable_system_file(PYTHON_PATH,PYTHON_SHA256);
  int py=open(PYTHON_PATH,O_RDONLY);if(py<0||hash_fd(py,digest,NULL,NULL)||strcmp(digest,PYTHON_SHA256))die("pinned Python stable-read SHA-256 drift");
  fcntl(sealed,F_SETFD,0);fcntl(watch,F_SETFD,0);fcntl(manifest_sealed,F_SETFD,0);fcntl(py,F_SETFD,0);
  char fd_s[32],watch_s[32],dev_s[32],ino_s[32],size_s[32],type_s[32],mode_s[32],uid_s[32],nlink_s[32],mtime_s[32],ctime_s[32],manifest_fd_s[32],manifest_dev_s[32],manifest_ino_s[32],manifest_size_s[32],manifest_type_s[32],manifest_mode_s[32],manifest_uid_s[32],manifest_nlink_s[32],manifest_mtime_s[32],manifest_ctime_s[32],py_path[64];
  snprintf(fd_s,sizeof(fd_s),"%d",sealed);snprintf(watch_s,sizeof(watch_s),"%d",watch);snprintf(dev_s,sizeof(dev_s),"%llu",(unsigned long long)before.st_dev);snprintf(ino_s,sizeof(ino_s),"%llu",(unsigned long long)before.st_ino);snprintf(size_s,sizeof(size_s),"%llu",(unsigned long long)before.st_size);snprintf(type_s,sizeof(type_s),"%u",(unsigned)(before.st_mode&S_IFMT));snprintf(mode_s,sizeof(mode_s),"%u",(unsigned)(before.st_mode&07777));snprintf(uid_s,sizeof(uid_s),"%u",(unsigned)before.st_uid);snprintf(nlink_s,sizeof(nlink_s),"%llu",(unsigned long long)before.st_nlink);snprintf(mtime_s,sizeof(mtime_s),"%lld",(long long)before.st_mtim.tv_nsec+(long long)before.st_mtim.tv_sec*1000000000LL);snprintf(ctime_s,sizeof(ctime_s),"%lld",(long long)before.st_ctim.tv_nsec+(long long)before.st_ctim.tv_sec*1000000000LL);snprintf(py_path,sizeof(py_path),"/proc/self/fd/%d",py);
  snprintf(manifest_fd_s,sizeof(manifest_fd_s),"%d",manifest_sealed);snprintf(manifest_dev_s,sizeof(manifest_dev_s),"%llu",(unsigned long long)manifest_before.st_dev);snprintf(manifest_ino_s,sizeof(manifest_ino_s),"%llu",(unsigned long long)manifest_before.st_ino);snprintf(manifest_size_s,sizeof(manifest_size_s),"%llu",(unsigned long long)manifest_before.st_size);snprintf(manifest_type_s,sizeof(manifest_type_s),"%u",(unsigned)(manifest_before.st_mode&S_IFMT));snprintf(manifest_mode_s,sizeof(manifest_mode_s),"%u",(unsigned)(manifest_before.st_mode&07777));snprintf(manifest_uid_s,sizeof(manifest_uid_s),"%u",(unsigned)manifest_before.st_uid);snprintf(manifest_nlink_s,sizeof(manifest_nlink_s),"%llu",(unsigned long long)manifest_before.st_nlink);snprintf(manifest_mtime_s,sizeof(manifest_mtime_s),"%lld",(long long)manifest_before.st_mtim.tv_nsec+(long long)manifest_before.st_mtim.tv_sec*1000000000LL);snprintf(manifest_ctime_s,sizeof(manifest_ctime_s),"%lld",(long long)manifest_before.st_ctim.tv_nsec+(long long)manifest_before.st_ctim.tv_sec*1000000000LL);
  if(clearenv()||setenv("PATH","/usr/bin:/bin",1)||setenv("LANG","C.UTF-8",1)||setenv("LC_ALL","C.UTF-8",1)||setenv("TZ","UTC",1)||setenv("PUPROJ_V12_BOOTSTRAP_SHA256",self_expected,1)||setenv("PUPROJ_V12_PYTHON_SHA256",PYTHON_SHA256,1))die("sanitized environment setup failed");
  char pycache_arg[256];snprintf(pycache_arg,sizeof(pycache_arg),"pycache_prefix=%s",PYCACHE_PREFIX);
  char *child[]={py_path,"-I","-S","-B","-X",pycache_arg,"-c",(char*)LOADER,fd_s,(char*)launcher_expected,(char*)launcher,watch_s,dev_s,ino_s,size_s,type_s,mode_s,uid_s,nlink_s,mtime_s,ctime_s,manifest_fd_s,(char*)manifest_expected,(char*)manifest_path,manifest_dev_s,manifest_ino_s,manifest_size_s,manifest_type_s,manifest_mode_s,manifest_uid_s,manifest_nlink_s,manifest_mtime_s,manifest_ctime_s,(char*)mode,NULL};
  free(raw);free(manifest_raw);close(src);close(manifest_src);execve(py_path,child,environ);die("pinned Python exec failed");return 70;
}
