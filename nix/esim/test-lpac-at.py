#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Exercise actual lpac AT callbacks and Unix transport with injected public IO.

Run on the build machine, even for cross builds. --reference-source optionally
proves that the same cases reject the original upstream callback at runtime.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile


def function(source, name):
    match = re.search(r"^(?:static )?(?:inline )?(?:int|void|char \*)\s*" + name +
                      r"\([^;]+?\) \{.*?^}\n", source, re.M | re.S)
    if not match:
        raise RuntimeError("missing production function " + name)
    return match.group()


def structure(source, name):
    return re.search(r"^struct " + name + r" \{.*?^}(?: __attribute__\(\(packed\)\))?;", source, re.M | re.S).group()


HEAD = r'''
#include <assert.h>
#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdbool.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
static void cleanup_free(void *p) { free(*(void **)p); }
#define _cleanup_free_ __attribute__((cleanup(cleanup_free)))
#define AT_DEBUG_TX(line) ((void)(line))
#define ENV_AT_DEVICE "fixture-device"
#define getenv_or_default(name, fallback) ((void)(name), (fallback))
struct euicc_ctx;
'''

BACKEND_IO = r'''
static unsigned commands, expects, opens, closes, channel_opens;
static unsigned write_fail_at, reply_fail_at;
static bool open_fail;
static const char *reply;
static char command[256];
static unsigned duplications, fail_duplication_at;
static char *fixture_strdup(const char *value) {
 duplications++; if(duplications==fail_duplication_at) { errno=ENOMEM; return NULL; }
 return strdup(value);
}
#define strdup fixture_strdup
static int at_device_open(struct at_userdata *data, const char *device) {
 (void)device; opens++; if(open_fail)return -1; data->fd=42; return 0;
}
static int at_device_close(struct at_userdata *data) { closes++; data->fd=-1; return 0; }
static int at_write_command(struct at_userdata *data, const char *value) {
 assert(data->fd==42); commands++; assert(strlen(value)<sizeof(command));
 strcpy(command,value);
 if(commands==write_fail_at) { errno=EIO; return -1; } return 0;
}
static int at_expect(struct at_userdata *data, char **response, const char *expected) {
 assert(data->fd==42); expects++; if(response)*response=NULL;
 if(commands==reply_fail_at)return -1;
 if(response && expected) { *response=reply?strdup(reply):NULL; }
 return 0;
}
'''

BACKEND_CASES = r'''
static void request_print(FILE *fp,const struct apdu_request *p,uint32_t n) {
 (void)fp; (void)p; (void)n;
}
static void response_print(FILE *fp,const struct apdu_response *p) { (void)fp; (void)p; }
#define euicc_apdu_request_print request_print
#define euicc_apdu_response_print response_print
'''

BACKEND_MAIN = r'''
int main(int argc,char **argv) {
 assert(argc==2);const char *name=argv[1];
 char *channels[AT_MAX_LOGICAL_CHANNELS+1]={0};
 struct at_userdata data={.default_device="fixture-device",.fd=-1,.channels=channels};
 struct euicc_apdu_interface iface={.connect=apdu_interface_connect,
  .disconnect=apdu_interface_disconnect,.logic_channel_open=fixture_channel_open,
  .transmit=apdu_interface_transmit,.userdata=&data};
 struct euicc_ctx ctx={.apdu={.interface=&iface}};
 uint8_t tx[]={0,0xA4,4,0};
 if(!strncmp(name,"connect-",8)) {
  if(!strcmp(name,"connect-open-error"))open_fail=true;
  else if(!strcmp(name,"connect-at-error"))reply_fail_at=1;
  else if(!strcmp(name,"connect-write-error"))write_fail_at=1;
  else if(!strncmp(name,"connect-probe-error-",20))reply_fail_at=(unsigned)atoi(name+20);
  else if(!strncmp(name,"connect-probe-write-",20))write_fail_at=(unsigned)atoi(name+20);
  else assert(!strcmp(name,"connect-success"));
  int ret=euicc_init(&ctx);
  if(!strcmp(name,"connect-success")) {
   assert(ret==0 && channel_opens==1 && commands==PROBE_COUNT && expects==commands);
   apdu_interface_disconnect(&ctx); assert(closes==1 && data.fd==-1);
  } else {
   assert(ret<0 && !channel_opens);
   unsigned failed=write_fail_at?write_fail_at:reply_fail_at;
   assert(commands==failed && expects==failed-(write_fail_at?1:0));
   assert(closes==(open_fail?0:1) && data.fd==-1);
  }
 } else if(!strncmp(name,"open-",5)) {
#if HAS_CHANNEL_CALLBACK
  data.fd=42; reply="7";
  if(!strcmp(name,"open-write-error"))write_fail_at=1;
  else if(!strcmp(name,"open-reply-error"))reply_fail_at=1;
  else if(!strcmp(name,"open-cleanup-write-error")) {
   channels[20]=strdup("old"); write_fail_at=1;
  } else if(!strcmp(name,"open-cleanup-reply-error")) {
   channels[20]=strdup("old"); reply_fail_at=1;
  } else if(!strcmp(name,"open-registration-error")) {
   fail_duplication_at=2;
  } else if(!strncmp(name,"open-invalid-",13)) {
   const char *bad[]={"", "x", "7,9", "7\rAT", "\"7\"", "-1", "+7", "7.1"};
   unsigned index=(unsigned)atoi(name+13); assert(index<sizeof(bad)/sizeof(bad[0])); reply=bad[index];
  } else assert(!strcmp(name,"open-success"));
  int id=apdu_interface_logic_channel_open(&ctx,tx,sizeof(tx));
  if(!strcmp(name,"open-success")) {
   assert(id>0 && commands==1 && expects==1 && channels[id] && !strcmp(channels[id],"7"));
   apdu_interface_logic_channel_close(&ctx,id); assert(!channels[id] && commands==2 && expects==2);
  } else if(!strcmp(name,"open-registration-error")) {
   assert(id<0 && commands==2 && expects==2 && !channels[1]);
   assert(!strcmp(command,"AT+CCHC=7\r\n"));
  } else {
   assert(id<0 && commands==1 && expects==(write_fail_at?0:1));
   if(channels[20])assert(!strcmp(channels[20],"old"));
  }
#else
  assert(!"channel case not applicable");
#endif
 } else if(!strcmp(name,"channel-transaction")) {
  channels[1]=strdup("old");char *old=channels[1];fail_duplication_at=duplications+1;
  assert(at_channel_set(&data,1,"new")<0 && channels[1]==old && !strcmp(channels[1],"old"));
 } else {
  data.fd=42; channels[1]=strdup("7");ctx.apdu._internal.logic_channel=1;
  uint8_t *rx=(uint8_t *)1; uint32_t n=123;
  if(!strcmp(name,"transmit-write-error")) {
   write_fail_at=1;assert(apdu_interface_transmit(&ctx,&rx,&n,tx,sizeof(tx))<0);
   assert(!rx && !n && commands==1 && !expects);
  } else if(!strcmp(name,"transmit-reply-error")) {
   reply_fail_at=1;reply="4,\"9000\"";
   assert(apdu_interface_transmit(&ctx,&rx,&n,tx,sizeof(tx))<0 && !rx && !n && expects==1);
  } else if(!strcmp(name,"transmit-overflow")) {
   assert(apdu_interface_transmit(&ctx,&rx,&n,tx,UINT32_MAX)<0 && !rx && !n && !commands && !expects);
  } else if(!strcmp(name,"transmit-no-channel")) {
#if HAS_CHANNEL_CALLBACK
   free(channels[1]);channels[1]=NULL;
   assert(apdu_interface_transmit(&ctx,&rx,&n,tx,sizeof(tx))<0 && !rx && !n && !commands && !expects);
#else
   assert(!"channel case not applicable");
#endif
  } else if(!strncmp(name,"invalid-",8)) {
   const char *bad[]={NULL,"4","4,\"","4,\"9000","4,9000\"","4,\"9000\",x",
    "6,\"9000\"","2,\"9000\"","5,\"90000\"","x,\"9000\"","-4,\"9000\"",
    "184467440737095516160,\"9000\"","4,\"90zz\"","4,\"90\xff\x80\"",
    "0,\"\"","2,\"90\"","4,\"90 0\"","4,,\"9000\"","4,\"9000\"junk"};
   unsigned index=(unsigned)atoi(name+8);assert(index<sizeof(bad)/sizeof(bad[0]));reply=bad[index];
   assert(apdu_interface_transmit(&ctx,&rx,&n,tx,sizeof(tx))<0 && !rx && !n);
  } else {
   uint8_t expected[]={0x90,0};
   if(!strcmp(name,"valid-quoted"))reply="4,\"9000\"";
   else if(!strcmp(name,"valid-unquoted"))reply="4,9000";
   else if(!strcmp(name,"valid-whitespace"))reply=" \t4 \t, \t\"9000\" \t";
   else if(!strcmp(name,"valid-status-error")) {reply="4,\"6A82\"";expected[0]=0x6a;expected[1]=0x82;}
   else if(!strcmp(name,"valid-status-more")) {reply="4,\"6100\"";expected[0]=0x61;}
   else if(!strcmp(name,"valid-data"))reply="8,\"aBcd9000\"";
   else assert(!"unknown fixture case");
   struct apdu_response result;
   assert(euicc_apdu_transmit(&ctx,&result,(struct apdu_request *)tx,sizeof(tx))==0);
   assert(result.sw1==expected[0] && result.sw2==expected[1]);
   assert(result.length==(!strcmp(name,"valid-data")?2:0));
   if(result.length)assert(result.data[0]==0xab && result.data[1]==0xcd);
   free(result.data); assert(commands==1 && expects==1);
  }
 }
 for(unsigned i=0;i<=AT_MAX_LOGICAL_CHANNELS;i++)free(channels[i]);
 puts("LPAC_AT_BACKEND_PASS");return 0;
}
'''


def backend_source(root, backend):
    read = lambda name: (root / name).read_text()
    helper = read("driver/apdu/at_helpers.c")
    bodies = "\n".join(function(helper, name) for name in
                       ("at_channel_get", "at_channel_set", "at_channel_next_id", "at_emit_command"))
    if re.search(r"^int at_parse_apdu_response\(", helper, re.M):
        bodies += function(helper, "at_parse_apdu_response")
    text = HEAD + structure(read("driver/apdu/at_cmd.h"), "at_userdata")
    text += "\n" + re.search(r"^#define AT_MAX_LOGICAL_CHANNELS .+$", read("driver/apdu/at_cmd.h"), re.M).group()
    text += "\n" + structure(read("euicc/interface.h"), "euicc_apdu_interface")
    text += "\n" + structure(read("euicc/euicc.h"), "euicc_ctx") + "\n"
    text += "\n".join(function(read("euicc/hexutil.c"), name) for name in
                      ("euicc_hexutil_bin2hex", "euicc_hexutil_hex2bin_r"))
    text += BACKEND_IO + bodies
    driver = read("driver/apdu/" + backend)
    text += "\n".join(function(driver, name) for name in
                      ("apdu_interface_connect", "apdu_interface_disconnect", "apdu_interface_transmit"))
    if backend == "at_etsi.c":
        text += "\n".join(function(driver, name) for name in
                          ("apdu_interface_logic_channel_open", "apdu_interface_logic_channel_close"))
    text += r'''
static int fixture_channel_open(struct euicc_ctx *ctx,const uint8_t *aid,uint8_t n) {
 (void)ctx;(void)aid;(void)n;channel_opens++;return 1;
}
'''
    text += "\n" + re.search(r"^#define ISD_R_AID .+$", read("euicc/euicc.c"), re.M).group() + "\n"
    text += function(read("euicc/euicc.c"), "euicc_init")
    private = read("euicc/interface.private.h")
    text += structure(private, "apdu_request") + ";\n" + structure(private, "apdu_response") + "\n"
    text += BACKEND_CASES + function(read("euicc/interface.c"), "euicc_apdu_transmit")
    text += f"\n#define PROBE_COUNT {4 if backend == 'at_etsi.c' else 2}\n"
    text += f"#define HAS_CHANNEL_CALLBACK {1 if backend == 'at_etsi.c' else 0}\n" + BACKEND_MAIN
    return "#define AT_BUFFER_SIZE 20480\n" + text


BACKEND_TESTS = ["connect-success", "connect-open-error", "connect-at-error", "connect-write-error",
                 "connect-probe-error-2", "connect-probe-write-2", "transmit-write-error",
                 "transmit-reply-error", "transmit-overflow", "channel-transaction"]
BACKEND_TESTS += ["invalid-" + str(i) for i in range(19)]
BACKEND_TESTS += ["valid-quoted", "valid-unquoted", "valid-whitespace", "valid-status-error",
                 "valid-status-more", "valid-data"]
ETSI_TESTS = ["connect-probe-error-3", "connect-probe-write-3", "connect-probe-error-4",
              "connect-probe-write-4", "transmit-no-channel", "open-success", "open-write-error",
              "open-reply-error", "open-cleanup-write-error", "open-cleanup-reply-error", "open-registration-error"]
ETSI_TESTS += ["open-invalid-" + str(i) for i in range(8)]
OLD_TESTS = ["connect-at-error", "connect-write-error", "transmit-write-error", "invalid-1", "invalid-6"]


TRANSPORT_PREFIX = r'''
#include <assert.h>
#include <errno.h>
#include <poll.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
static void cleanup_free(char **p) {free(*p);}
#define _cleanup_free_ __attribute__((cleanup(cleanup_free)))
#define AT_DEBUG_RX(line) ((void)(line))
static unsigned writes, reads, polls, terminal_polls, write_error_call;
static int write_errno, read_errno, poll_errno;
static bool write_zero, read_zero, real_io;
static short terminal_events;
static const char *incoming;
static size_t input_position, output_length;
static char output[256];
static ssize_t transport_write(int fd,const void *buffer,size_t length) {
 writes++;
 if(write_errno && (!write_error_call || writes==write_error_call)) {errno=write_errno;write_errno=0;return -1;}
 if(write_zero)return 0;
 size_t n=length<3?length:3;
 if(real_io)return write(fd,buffer,n);
 assert(output_length+n<=sizeof(output));
 memcpy(output+output_length,buffer,n);output_length+=n;return n;
}
static int transport_poll(struct pollfd *fd,nfds_t count,int timeout) {
 polls++;assert(count==1 && timeout==-1 && fd->events==POLLIN);
 if(poll_errno) {errno=poll_errno;poll_errno=0;return -1;}
 if(real_io)return poll(fd,count,timeout);
 fd->revents=terminal_events;
 if(incoming && incoming[input_position])fd->revents|=POLLIN;
 else {
  /* An immediate terminal event must not be polled repeatedly. */
  assert(++terminal_polls==1);
  assert(terminal_events);
 }
 return 1;
}
static ssize_t transport_read(int fd,void *buffer,size_t length) {
 reads++;
 if(read_errno) {errno=read_errno;read_errno=0;return -1;}
 if(read_zero)return 0;
 size_t n=length<3?length:3;
 if(real_io)return read(fd,buffer,n);
 assert(incoming);
 size_t remaining=strlen(incoming+input_position);
 if(n>remaining)n=remaining;
 memcpy(buffer,incoming+input_position,n);input_position+=n;return n;
}
#define write transport_write
#define poll transport_poll
#define read transport_read
'''
TRANSPORT_MAIN = r'''
#undef write
#undef poll
#undef read
static void expect_response(int fd,const char *expected,bool success,const char *value) {
 struct at_userdata data={.fd=fd};char *response=(char *)1;
 assert(at_expect(&data,&response,expected)==(success?0:-1));
 if(success && value)assert(response && !strcmp(response,value));
 else assert(!response);
 free(response);
}
int main(int argc,char **argv) {
 assert(argc==2);const char *name=argv[1];
 const char *command="AT+VALUE?\r\n";
 struct at_userdata data={.fd=42};
 if(!strcmp(name,"write-fragments") || !strcmp(name,"write-eintr") || !strcmp(name,"write-eintr-first")) {
  if(!strcmp(name,"write-eintr")) {write_errno=EINTR;write_error_call=2;}
  if(!strcmp(name,"write-eintr-first"))write_errno=EINTR;
  assert(at_write_command(&data,command)==0);
  assert(output_length==strlen(command) && !memcmp(output,command,output_length));
  assert(writes>=4);
 } else if(!strcmp(name,"write-zero")) {
  write_zero=true;assert(at_write_command(&data,command)==-1 && writes==1);
 } else if(!strcmp(name,"write-error")) {
  write_errno=EIO;assert(at_write_command(&data,command)==-1 && writes==1);
 } else if(!strcmp(name,"write-partial-error")) {
  write_errno=EIO;write_error_call=2;
  assert(at_write_command(&data,command)==-1 && writes==2 && output_length==3);
 } else if(!strcmp(name,"write-invalid")) {
  data.fd=-1;assert(at_write_command(&data,command)==-1 && !writes);
 } else if(!strcmp(name,"write-empty")) {
  assert(at_write_command(&data,"")==0 && !output_length);
 } else if(!strcmp(name,"parse-fragments") || !strcmp(name,"poll-eintr") ||
           !strcmp(name,"read-eintr") || !strcmp(name,"hup-tail")) {
  incoming="\r\nnoise\r\n+VALUE:    data\r\nOK\r\n";
  if(!strcmp(name,"poll-eintr"))poll_errno=EINTR;
  if(!strcmp(name,"read-eintr"))read_errno=EINTR;
  if(!strcmp(name,"hup-tail"))terminal_events=POLLHUP;
  expect_response(42,"+VALUE:",true,"data");assert(polls>1 && reads>1);
 } else if(!strcmp(name,"parse-retained")) {
  struct at_userdata retained={.fd=42};char *response=NULL;
  const char *two="+VALUE: one\r\nOK\r\n+VALUE: two\r\nOK\r\n";
  memcpy(retained.at_read_buffer,two,strlen(two));retained.at_read_buffer_len=strlen(two);
  assert(at_expect(&retained,&response,"+VALUE:")==0 && !strcmp(response,"one"));free(response);
  assert(at_expect(&retained,&response,"+VALUE:")==0 && !strcmp(response,"two"));free(response);
  assert(!polls && !reads && !retained.at_read_buffer_len);
 } else if(!strcmp(name,"response-error") || !strcmp(name,"response-cme-error")) {
  incoming=!strcmp(name,"response-cme-error")?"+VALUE: data\r\n+CME ERROR: 10\r\n":"+VALUE: data\r\nERROR\r\n";expect_response(42,"+VALUE:",false,NULL);
 } else if(!strcmp(name,"poll-error")) {
  poll_errno=EIO;expect_response(42,NULL,false,NULL);assert(polls==1 && !reads);
 } else if(!strcmp(name,"read-error") || !strcmp(name,"read-zero")) {
  incoming="OK\r\n";if(!strcmp(name,"read-error"))read_errno=EIO;else read_zero=true;
  expect_response(42,NULL,false,NULL);assert(polls==1 && reads==1);
 } else if(!strcmp(name,"hup") || !strcmp(name,"err") || !strcmp(name,"nval") ||
           !strcmp(name,"hup-partial")) {
  terminal_events=!strcmp(name,"err")?POLLERR:!strcmp(name,"nval")?POLLNVAL:POLLHUP;
  if(!strcmp(name,"hup-partial"))incoming="OK";
  expect_response(42,NULL,false,NULL);assert(terminal_polls==1);
 } else if(!strcmp(name,"closed-userdata")) {
  int pipefd[2];assert(pipe(pipefd)==0);data.fd=pipefd[0];
  assert(at_device_close(&data)==0 && data.fd==-1 && close(pipefd[1])==0);real_io=true;
  char *response=(char *)1;
  assert(at_expect(&data,&response,NULL)==-1 && !response && !polls && !reads);
 } else if(!strcmp(name,"real-hup") || !strcmp(name,"real-nval") ||
           !strcmp(name,"real-hup-tail") || !strcmp(name,"real-write")) {
  int pipefd[2];assert(pipe(pipefd)==0);real_io=true;
  if(!strcmp(name,"real-write")) {
   data.fd=pipefd[1];write_errno=EINTR;write_error_call=2;
   assert(at_write_command(&data,command)==0);assert(close(pipefd[1])==0);
   char received[64]={0};ssize_t n=read(pipefd[0],received,sizeof(received));
   assert(n==(ssize_t)strlen(command) && !memcmp(received,command,(size_t)n));
   assert(close(pipefd[0])==0);
  } else {
   if(!strcmp(name,"real-hup-tail"))assert(write(pipefd[1],"OK\r\n",4)==4);
   assert(close(pipefd[1])==0);
   if(!strcmp(name,"real-nval"))assert(close(pipefd[0])==0);
   expect_response(pipefd[0],NULL,!strcmp(name,"real-hup-tail"),NULL);
   if(strcmp(name,"real-nval"))assert(close(pipefd[0])==0);
  }
 } else assert(!"unknown fixture case");
 puts("AT_TRANSPORT_CASE_PASS");return 0;
}
'''
TRANSPORT_TESTS = ['write-fragments', 'write-eintr', 'write-eintr-first', 'write-zero', 'write-error', 'write-partial-error', 'write-invalid', 'write-empty', 'parse-fragments', 'parse-retained', 'poll-eintr', 'read-eintr', 'hup-tail', 'response-error', 'poll-error', 'read-error', 'read-zero', 'hup', 'err', 'nval', 'hup-partial', 'closed-userdata', 'real-hup', 'real-nval', 'real-hup-tail', 'real-write', 'response-cme-error']

def transport_source(root):
    source = (root / "driver/apdu/at_cmd_unix.c").read_text()
    header = (root / "driver/apdu/at_cmd.h").read_text()
    buffer_size = re.search(r"^#define AT_BUFFER_SIZE .+$", header, re.M).group()
    before, after = TRANSPORT_PREFIX.split("static unsigned", 1)
    bodies = "\n".join(function(source, name) for name in ("at_write_command", "at_expect", "at_device_close"))
    return buffer_size + "\n" + before + structure(header, "at_userdata") + "\nstatic unsigned" + after + bodies + TRANSPORT_MAIN


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--reference-source", type=Path)
    parser.add_argument("--out", type=Path, help="retain generated actual-source harness and results")
    args = parser.parse_args()
    temporary = tempfile.TemporaryDirectory(prefix="lpac-at-")
    out = args.out or Path(temporary.name)
    out.mkdir(exist_ok=True, parents=True)
    compiler = shlex.split(os.environ.get("HOSTCC", os.environ.get("CC", "cc")))
    flags = ["-std=gnu11", "-Wall", "-Wextra", "-Werror", "-O0", "-g", "-fsanitize=address,undefined",
             "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    proof = {"start": datetime.datetime.now(datetime.timezone.utc).isoformat(), "results": []}
    roots = [("candidate", args.source)]
    if args.reference_source:
        roots.append(("original", args.reference_source))
    for variant, root in roots:
        for backend in ("at_etsi.c", "at_etsi_csim.c", "transport.c"):
            label = variant + "-" + backend[:-2]
            path = out / (label + ".c")
            path.write_text(transport_source(root) if backend == "transport.c" else backend_source(root, backend))
            binary = out / label
            command = compiler + flags + shlex.split(os.environ.get("HOSTCFLAGS", "")) + [str(path), "-o", str(binary)]
            build = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            (out / (label + "-build.log")).write_bytes(build.stdout)
            result = {"variant": variant, "backend": backend, "compile": command, "compile_exit": build.returncode,
                      "generated_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "cases": []}
            proof["results"].append(result)
            if build.returncode:
                print(build.stdout.decode(errors="replace"))
                continue
            if backend == "transport.c":
                cases = ["write-fragments", "write-eintr", "hup", "response-cme-error"] if variant == "original" else TRANSPORT_TESTS
                marker = b"AT_TRANSPORT_CASE_PASS"
            else:
                cases = OLD_TESTS + (["open-registration-error", "open-invalid-1"] if backend == "at_etsi.c" else []) if variant == "original" else BACKEND_TESTS + (ETSI_TESTS if backend == "at_etsi.c" else [])
                marker = b"LPAC_AT_BACKEND_PASS"
            for case in cases:
                try:
                    run = subprocess.run([str(binary), case], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=3)
                    code, log, timed_out = run.returncode, run.stdout, False
                except subprocess.TimeoutExpired as error:
                    code, log, timed_out = None, error.stdout or b"", True
                (out / (label + "-" + case + ".log")).write_bytes(log)
                passed = not timed_out and code == 0 and marker in log
                expected = passed if variant == "candidate" else (not timed_out and code != 0 and
                           (b"Assertion" in log or b"AddressSanitizer" in log))
                result["cases"].append({"case": case, "exit": code, "timed_out": timed_out,
                                        "expected": expected, "log_sha256": hashlib.sha256(log).hexdigest()})
                print(label, case, code, "expected", expected, flush=True)
    proof["end"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    proof["terminal"] = True
    proof["passed"] = all(r["compile_exit"] == 0 and r["cases"] and
                          all(c["expected"] for c in r["cases"]) for r in proof["results"])
    (out / "result.json").write_text(json.dumps(proof, indent=2) + "\n")
    temporary.cleanup()
    return 0 if proof["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
