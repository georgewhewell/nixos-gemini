#!/usr/bin/env python3
"""Exercise the capture client against the ALSA UAPI, including cleanup failures."""
from pathlib import Path
import os
import subprocess
import tempfile

source = Path(__file__).with_name('audio-capture.c').resolve()
program = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <sound/asound.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>
static int fake_open(const char *, int, ...);
static int fake_close(int);
static int fake_ioctl(int, unsigned long, void *);
static int fake_poll(struct pollfd *, nfds_t, int);
static int fake_clock_gettime(clockid_t, struct timespec *);
#define open fake_open
#define close fake_close
#define ioctl fake_ioctl
#define poll fake_poll
#define clock_gettime fake_clock_gettime
#define main audio_main
'''
program += '#include "' + str(source) + '"\n'
program += r'''
#undef main
#undef open
#undef close
#undef ioctl
#undef poll
#undef clock_gettime
#define CONTROL_COUNT (sizeof(controls) / sizeof(controls[0]))
static unsigned int calls, failure, mode, opened, frames_read, reads, polls;
static unsigned long milliseconds;
static bool ctl_open, pcm_open, configured, prepared, started, dropped, restoring;
static long values[CONTROL_COUNT][2], original[CONTROL_COUNT][2];

static unsigned int count(unsigned int index) { return index == 7 ? 2 : 1; }
static int fake_open(const char *path, int flags, ...) {
 opened++;
 if(opened==1) {
  assert(!strcmp(path,"/dev/snd/controlC0"));
  assert((flags&O_ACCMODE)==O_RDWR || (flags&O_ACCMODE)==O_RDONLY);
  if(mode==24){errno=EIO;return -1;}
  ctl_open=true;return 10;
 }
 assert(!strcmp(path,"/dev/snd/pcmC0D3c") && (flags&O_NONBLOCK));
 if(mode==25){errno=EIO;return -1;}
 pcm_open=true;return 11;
}
static int fake_close(int fd) {
 if(fd==10){assert(ctl_open);ctl_open=false;}
 else {assert(fd==11 && pcm_open);pcm_open=false;restoring=true;}
 if((mode==20 && fd==11)||(mode==21 && fd==10)){errno=EIO;return -1;}
 return 0;
}
static int fake_ioctl(int fd, unsigned long raw, void *arg) {
 unsigned int request=(unsigned int)raw;
 assert((fd==10 && ctl_open)||(fd==11 && pcm_open));
 bool fail=++calls==failure;
 if(fail && request!=(unsigned int)SNDRV_CTL_IOCTL_ELEM_WRITE){errno=EIO;return -1;}
 switch(request) {
 case (unsigned int)SNDRV_CTL_IOCTL_CARD_INFO: {
  struct snd_ctl_card_info *v=arg;
  strcpy((char *)v->name,mode==22?"other-card":"mt6797-mt6351");break;
 }
 case (unsigned int)SNDRV_CTL_IOCTL_PCM_NEXT_DEVICE: {
  int *v=arg;
  *v=mode==28?0:(*v<3?*v+1:-1);break;
 }
 case (unsigned int)SNDRV_CTL_IOCTL_PCM_INFO: {
  struct snd_pcm_info *v=arg;
  assert(v->stream==SNDRV_PCM_STREAM_CAPTURE);
  if(v->device<3){errno=ENOENT;return -1;}
  assert(v->device==3);
  strcpy((char *)v->id,mode==23?"Capture_10":"Capture_1 (*)");break;
 }
 case (unsigned int)SNDRV_CTL_IOCTL_ELEM_LIST: {
  struct snd_ctl_elem_list *v=arg;v->count=mode==26?4097:CONTROL_COUNT;
  if(v->space) {
   assert(v->space==CONTROL_COUNT);v->used=mode==27?CONTROL_COUNT+1:CONTROL_COUNT;
   for(unsigned int i=0;i<CONTROL_COUNT;i++) {
    v->pids[i].numid=i+1;strcpy((char *)v->pids[i].name,controls[i].name);
   }
  }break;
 }
 case (unsigned int)SNDRV_CTL_IOCTL_ELEM_INFO: {
  struct snd_ctl_elem_info *v=arg;unsigned int i=v->id.numid-1;
  assert(i<CONTROL_COUNT);
  v->access=SNDRV_CTL_ELEM_ACCESS_READ|SNDRV_CTL_ELEM_ACCESS_WRITE;v->count=count(i);
  v->type=i<2?SNDRV_CTL_ELEM_TYPE_BOOLEAN:(i==7?SNDRV_CTL_ELEM_TYPE_INTEGER:SNDRV_CTL_ELEM_TYPE_ENUMERATED);
  if(i>=2 && i<7) {
   assert(v->value.enumerated.item<2);v->value.enumerated.items=2;
   strcpy(v->value.enumerated.name,v->value.enumerated.item?controls[i].enum_item:"Idle");
  } else if(i==7) {
   v->value.integer.min=0;v->value.integer.max=4;v->value.integer.step=1;
  }break;
 }
 case (unsigned int)SNDRV_CTL_IOCTL_ELEM_READ: {
  struct snd_ctl_elem_value *v=arg;unsigned int i=v->id.numid-1;
  assert(i<CONTROL_COUNT);
  for(unsigned int j=0;j<count(i);j++) {
   long value=values[i][j];
   if(mode==19 && i==0 && !restoring && value==1)value=0;
   if(i<2 || i==7)v->value.integer.value[j]=value;
   else v->value.enumerated.item[j]=(unsigned int)value;
  }break;
 }
 case (unsigned int)SNDRV_CTL_IOCTL_ELEM_WRITE: {
  struct snd_ctl_elem_value *v=arg;unsigned int i=v->id.numid-1;
  assert(i<CONTROL_COUNT && !pcm_open);
  for(unsigned int j=0;j<count(i);j++)
   values[i][j]=i<2 || i==7?v->value.integer.value[j]:(long)v->value.enumerated.item[j];
  /* The write may take effect before its error is returned. */
  if(fail){errno=EIO;return -1;}
  break;
 }
 case (unsigned int)SNDRV_PCM_IOCTL_HW_PARAMS: {
  struct snd_pcm_hw_params *v=arg;
  for(unsigned int i=0;i<CONTROL_COUNT;i++)
   for(unsigned int j=0;j<count(i);j++)assert(values[i][j]==1);
  assert(v->masks[SNDRV_PCM_HW_PARAM_FORMAT-SNDRV_PCM_HW_PARAM_FIRST_MASK].bits[0]==(1U<<SNDRV_PCM_FORMAT_S16_LE));
  configured=true;
  if(mode==18)v->intervals[SNDRV_PCM_HW_PARAM_CHANNELS-SNDRV_PCM_HW_PARAM_FIRST_INTERVAL].min=1;
  break;
 }
 case (unsigned int)SNDRV_PCM_IOCTL_SW_PARAMS: {
  struct snd_pcm_sw_params *v=arg;
  assert(configured && v->avail_min==PERIOD_FRAMES && v->stop_threshold==BUFFER_FRAMES);
  assert(v->start_threshold>CAPTURE_FRAMES && v->start_threshold<=LONG_MAX);break;
 }
 case (unsigned int)SNDRV_PCM_IOCTL_PREPARE:assert(configured);prepared=true;break;
 case (unsigned int)SNDRV_PCM_IOCTL_START:assert(prepared && !started);started=true;break;
 case (unsigned int)SNDRV_PCM_IOCTL_STATUS: {
  struct snd_pcm_status *v=arg;
  if(dropped)v->state=mode==17?SNDRV_PCM_STATE_RUNNING:SNDRV_PCM_STATE_SETUP;
  else if(!started)v->state=mode==11?SNDRV_PCM_STATE_XRUN:SNDRV_PCM_STATE_PREPARED;
  else v->state=mode==12?SNDRV_PCM_STATE_XRUN:(mode==13?SNDRV_PCM_STATE_SUSPENDED:(mode==14?SNDRV_PCM_STATE_DISCONNECTED:SNDRV_PCM_STATE_RUNNING));
  v->appl_ptr=frames_read;
  if(mode==15 && started && !dropped)v->appl_ptr++;
  v->hw_ptr=frames_read+(started && !dropped?PERIOD_FRAMES:0);
  v->delay=v->hw_ptr-v->appl_ptr;break;
 }
 case (unsigned int)SNDRV_PCM_IOCTL_READI_FRAMES: {
  struct snd_xferi *v=arg;assert(started && !dropped && v->frames && v->frames<=PERIOD_FRAMES);
  reads++;
  if((mode==1 && reads==1)||mode==2){errno=EAGAIN;return -1;}
  if(mode==29 && reads==1){errno=EINTR;return -1;}
  if(mode==4){v->result=0;break;}
  if(mode==5){v->result=-EPIPE;break;}
  if(mode==6){v->result=v->frames+1;break;}
  unsigned int n=mode==3?(unsigned int)v->frames/2+1:(unsigned int)v->frames;
  int16_t *data=v->buf;
  for(unsigned int i=0;i<n*CHANNELS;i++)data[i]=mode==30?0:((i%2)?INT16_MIN:INT16_MAX);
  v->result=n;frames_read+=n;assert(frames_read<=CAPTURE_FRAMES);break;
 }
 case (unsigned int)SNDRV_PCM_IOCTL_DROP:
  if(mode==16){errno=EIO;return -1;}
  dropped=true;break;
 default:assert(!"unexpected ioctl");
 }
 return 0;
}
static int fake_poll(struct pollfd *pfd, nfds_t n, int timeout) {
 assert(n==1 && pfd->fd==11 && pfd->events==POLLIN && timeout>0);
 polls++;milliseconds+=mode==2?1000:1;
 pfd->revents=POLLIN;
 if(mode==7)pfd->revents|=POLLERR;
 if(mode==8)pfd->revents|=POLLHUP;
 if(mode==9)pfd->revents|=POLLNVAL;
 return mode==10?0:1;
}
static int fake_clock_gettime(clockid_t clock, struct timespec *t) {
 assert(clock==CLOCK_MONOTONIC);milliseconds++;
 t->tv_sec=milliseconds/1000;t->tv_nsec=(milliseconds%1000)*1000000;return 0;
}
static int run(unsigned int inject, unsigned int behavior) {
 calls=opened=frames_read=reads=polls=0;failure=inject;mode=behavior;milliseconds=0;
 ctl_open=pcm_open=configured=prepared=started=dropped=restoring=false;
 for(unsigned int i=0;i<CONTROL_COUNT;i++)
  for(unsigned int j=0;j<2;j++)values[i][j]=original[i][j]=i==7?3+(long)j:(long)(i%2);
 char *args[]={"capture","--stage","capture","--activate"};
 int result=audio_main(4,args);
 assert(!ctl_open && !pcm_open);
 for(unsigned int i=0;i<CONTROL_COUNT;i++)
  for(unsigned int j=0;j<count(i);j++)assert(values[i][j]==original[i][j]);
 return result;
}
int main(void) {
 assert(run(0,0)==EXIT_SUCCESS && frames_read==CAPTURE_FRAMES && dropped);
 unsigned int total=calls;
 for(unsigned int i=1;i<=total;i++)assert(run(i,0)==EXIT_FAILURE);
 for(unsigned int i=1;i<=30;i++) {
  int result=run(0,i);
  assert(result==((i==1 || i==3 || i==29 || i==30)?EXIT_SUCCESS:EXIT_FAILURE));
 }
 opened=0;
 char *args[]={"capture","--stage","capture"};
 assert(audio_main(3,args)==EXIT_FAILURE && !opened);
 puts("PASS: capture bounds, partial reads, EAGAIN/EINTR, timeout, PCM states, error readiness, quiet input, explicit activation and all returning ioctl/close failures; all eight controls restored");
}
'''
with tempfile.TemporaryDirectory(prefix='gemini-audio-capture-') as temporary:
    c = Path(temporary) / 'test.c'
    binary = Path(temporary) / 'test'
    c.write_text(program)
    subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-O1', '-g', '-fno-pie', '-no-pie', '-fsanitize=address,undefined',
                    str(c), '-o', str(binary)], check=True)
    result = subprocess.run([str(binary)], stderr=subprocess.PIPE, text=True)
    if result.returncode:
        print(result.stderr[-6000:])
    result.check_returncode()
