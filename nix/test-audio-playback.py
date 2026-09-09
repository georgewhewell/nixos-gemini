#!/usr/bin/env python3
"""Run the actual PCM helper with syscall adapters and failure injection."""
from pathlib import Path
import os
import subprocess
import tempfile

source = Path(__file__).with_name('audio-playback.c').resolve()
program = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
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
static unsigned int calls, failure, opened, mode, samples, control_writes, drained;
static unsigned long milliseconds;
static bool ctl_open, pcm_open, prepared, waited, drain_called, drain_finished;
static long values[4], original[4];
static int fake_open(const char *path, int flags, ...) {
 opened++;
 if(opened==1) {
  assert(!strcmp(path,"/dev/snd/controlC0") && flags==(O_RDWR|O_CLOEXEC));
  if(mode==10){errno=EIO;return -1;}
  ctl_open=true;return 10;
 }
 assert(!strcmp(path,"/dev/snd/pcmC0D0p") && (flags&O_NONBLOCK));
 if(mode==11){errno=EIO;return -1;}
 pcm_open=true;return 11;
}
static int fake_close(int fd) {
 if(fd==10){assert(ctl_open);ctl_open=false;}
 else {assert(fd==11 && pcm_open);pcm_open=false;}
 if(mode==12){errno=EIO;return -1;}
 return 0;
}
static int fake_ioctl(int fd, unsigned long raw, void *arg) {
 unsigned int request=(unsigned int)raw;
 assert((fd==10&&ctl_open)||(fd==11&&pcm_open));
 bool fail=++calls==failure;
 if(fail && request!=(unsigned int)SNDRV_CTL_IOCTL_ELEM_WRITE){errno=EIO;return -1;}
 switch(request) {
 case (unsigned int)SNDRV_CTL_IOCTL_CARD_INFO: {
  struct snd_ctl_card_info *v=arg;
  strcpy((char *)v->name,mode==8?"other-card":"mt6797-mt6351");break;
 }
 case (unsigned int)SNDRV_CTL_IOCTL_PCM_INFO: {
  struct snd_pcm_info *v=arg;
  assert(v->device==0 && v->stream==SNDRV_PCM_STREAM_PLAYBACK);
  strcpy((char *)v->id,mode==9?"Playback_10":"Playback_1 (*)");break;
 }
 case (unsigned int)SNDRV_CTL_IOCTL_ELEM_LIST: {
  struct snd_ctl_elem_list *v=arg;v->count=4;
  if(v->space) {
   assert(v->space==4);v->used=4;
   for(unsigned i=0;i<4;i++){v->pids[i].numid=i+1;strcpy((char *)v->pids[i].name,controls[i].name);}
  }break;
 }
 case (unsigned int)SNDRV_CTL_IOCTL_ELEM_INFO: {
  struct snd_ctl_elem_info *v=arg;unsigned i=v->id.numid-1;assert(i<4);
  v->access=SNDRV_CTL_ELEM_ACCESS_READ|SNDRV_CTL_ELEM_ACCESS_WRITE;v->count=1;
  v->type=i<2?SNDRV_CTL_ELEM_TYPE_BOOLEAN:SNDRV_CTL_ELEM_TYPE_ENUMERATED;
  if(i>=2) {
   assert(v->value.enumerated.item<2);
   v->value.enumerated.items=2;
   strcpy(v->value.enumerated.name,v->value.enumerated.item?"Audio Playback":"Open");
  }break;
 }
 case (unsigned int)SNDRV_CTL_IOCTL_ELEM_READ: {
  struct snd_ctl_elem_value *v=arg;unsigned i=v->id.numid-1;assert(i<4);
  if(i<2)v->value.integer.value[0]=values[i];else v->value.enumerated.item[0]=values[i];break;
 }
 case (unsigned int)SNDRV_CTL_IOCTL_ELEM_WRITE: {
  struct snd_ctl_elem_value *v=arg;unsigned i=v->id.numid-1;assert(i<4);
  assert(!pcm_open);control_writes++;
  values[i]=i<2?v->value.integer.value[0]:(long)v->value.enumerated.item[0];
  /* An error after changing state must still lead to restoration. */
  if(fail){errno=EIO;return -1;}
  break;
 }
 case (unsigned int)SNDRV_PCM_IOCTL_HW_PARAMS: {
  struct snd_pcm_hw_params *v=arg;
  for(unsigned i=0;i<4;i++)assert(values[i]==1);
  assert(v->intervals[SNDRV_PCM_HW_PARAM_PERIOD_SIZE-SNDRV_PCM_HW_PARAM_FIRST_INTERVAL].min==960);
  assert(v->intervals[SNDRV_PCM_HW_PARAM_BUFFER_SIZE-SNDRV_PCM_HW_PARAM_FIRST_INTERVAL].min==3840);
  break;
 }
 case (unsigned int)SNDRV_PCM_IOCTL_SW_PARAMS: {
  struct snd_pcm_sw_params *v=arg;
  assert(v->start_threshold==3840 && v->avail_min==960 && v->boundary>3840);break;
 }
 case (unsigned int)SNDRV_PCM_IOCTL_PREPARE:prepared=true;break;
 case (unsigned int)SNDRV_PCM_IOCTL_WRITEI_FRAMES: {
  struct snd_xferi *v=arg;assert(prepared && v->frames && v->frames<=960);
  if((mode==1 || mode==22) && !waited){errno=EAGAIN;return -1;}
  if(mode==2){errno=EAGAIN;return -1;}
  if(mode==3){v->result=0;break;}
  if(mode==4){v->result=-EPIPE;break;}
  if(mode==5){v->result=v->frames+1;break;}
  unsigned count=mode==6?(unsigned)v->frames/2+1:(unsigned)v->frames;
  const int16_t *data=v->buf;
  for(unsigned i=0;i<count;i++) {
   assert(abs(data[2*i])<=512 && data[2*i]==data[2*i+1]);
   if(samples==0 || samples==TONE_FRAMES-1)assert(data[2*i]==0);
   samples++;
  }
  v->result=count;break;
 }
 case (unsigned int)SNDRV_PCM_IOCTL_STATUS: {
  struct snd_pcm_status *v=arg;
  if(!drain_called)v->state=mode==18?SNDRV_PCM_STATE_XRUN:SNDRV_PCM_STATE_RUNNING;
  else if(!drain_finished)v->state=SNDRV_PCM_STATE_DRAINING;
  else if(mode==13)v->state=SNDRV_PCM_STATE_XRUN;
  else if(mode==14)v->state=SNDRV_PCM_STATE_SUSPENDED;
  else if(mode==15)v->state=SNDRV_PCM_STATE_DISCONNECTED;
  else v->state=SNDRV_PCM_STATE_SETUP;
  v->delay=v->state==SNDRV_PCM_STATE_SETUP?(mode==20?1:0):960;
  v->appl_ptr=samples;v->hw_ptr=samples-v->delay;
  break;
 }
 case (unsigned int)SNDRV_PCM_IOCTL_DRAIN:
  assert(samples==TONE_FRAMES && !drain_called);
  drain_called=true;drained++;
  /* pcm_native.c snd_pcm_drain: O_NONBLOCK always returns EAGAIN. */
  errno=EAGAIN;return -1;
 default:assert(!"unexpected ioctl");
 }
 return 0;
}
static int fake_poll(struct pollfd *pfd, nfds_t n, int timeout) {
 assert(n==1 && pfd->fd==11 && timeout>0);
 waited=true;
 milliseconds+=(mode==2 || mode==7)?1000:1;
 if(drain_called) {
  drain_finished=mode!=7;
  /* snd_pcm_poll: playback DRAINING is not ready; SETUP wakes with ERR. */
  pfd->revents=POLLOUT|POLLERR;
  if(mode==16)pfd->revents=POLLHUP;
  if(mode==17)pfd->revents=POLLNVAL;
 } else pfd->revents=mode==22?(POLLOUT|POLLERR):POLLOUT;
 return 1;
}
static int fake_clock_gettime(clockid_t clock, struct timespec *t) {
 assert(clock==CLOCK_MONOTONIC);milliseconds++;
 t->tv_sec=milliseconds/1000;t->tv_nsec=(milliseconds%1000)*1000000;return 0;
}
static int run(unsigned inject, unsigned behavior) {
 calls=opened=samples=control_writes=drained=0;failure=inject;mode=behavior;
 ctl_open=pcm_open=prepared=waited=drain_called=drain_finished=false;milliseconds=0;
 for(unsigned i=0;i<4;i++)values[i]=original[i]=(i%2);
 char *args[]={"audio","--activate"};
 int result=audio_main(2,args);
 assert(!ctl_open && !pcm_open);
 for(unsigned i=0;i<4;i++)assert(values[i]==original[i]);
 return result;
}
int main(void) {
 assert(run(0,0)==EXIT_SUCCESS && samples==TONE_FRAMES && drained==1);
 unsigned total=calls;
 for(unsigned i=1;i<=total;i++)assert(run(i,0)==EXIT_FAILURE);
 assert(run(0,1)==EXIT_SUCCESS && waited);
 assert(run(0,6)==EXIT_SUCCESS && samples==TONE_FRAMES);
 for(unsigned i=2;i<=18;i++)if(i!=6)assert(run(0,i)==EXIT_FAILURE);
 assert(run(0,20)==EXIT_FAILURE);assert(run(0,22)==EXIT_FAILURE);
 opened=0;
 char *args[]={"audio"};assert(audio_main(1,args)==EXIT_FAILURE && !opened);
 puts("PASS: real helper recognizes nonblocking drain EAGAIN then SETUP/POLLERR; rejects XRUN, suspended/disconnected, bad delay and write-side POLLERR; all syscall failures restore controls and waveform remains bounded");
}
'''
with tempfile.TemporaryDirectory(prefix='gemini-audio-playback-') as temporary:
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
