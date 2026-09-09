#!/usr/bin/env python3
"""Exercise the production MT6351 detector with register/IRQ/work adapters."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

kernel = Path(sys.argv[1]).resolve()
src = (kernel / 'sound/soc/codecs/mt6351-accdet.c').read_text()
# Keep every production function, including probe and teardown. Only kernel
# includes are replaced; the physical register protocol is modeled below.
src = '\n'.join(line for line in src.splitlines() if not line.startswith('#include'))
prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
#define BIT(n) (1u << (n))
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define GFP_KERNEL 0
#define IRQF_ONESHOT 1
#define IRQF_NO_AUTOEN 2
#define IRQ_HANDLED 1
#define EPROBE_DEFER 517
#define SND_JACK_HEADPHONE 1
#define SND_JACK_MICROPHONE 2
#define SND_JACK_HEADSET 3
#define MT6351_AUDENC_ANA_CON10 0x0d1c
#define MT6351_AUDENC_ANA_CON11 0x0d1e
#define ERR_PTR(v) ((void *)(intptr_t)(v))
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define container_of(p,t,m) ((t *)((char *)(p) - offsetof(t,m)))
#define to_delayed_work(p) container_of(p, struct delayed_work, work)
#define dev_err(dev,...) ((void)(dev))
#define dev_info(dev,...) ((void)(dev))
#define msecs_to_jiffies(v) (v)
#define time_before(a,b) ((long)((a)-(b)) < 0)
static unsigned long jiffies;
struct device { int unused; };
struct platform_device { struct device dev; } pdev;
struct mutex { int held; };
struct work_struct { int unused; };
struct delayed_work { struct work_struct work; void (*fn)(struct work_struct *); bool pending; unsigned int delay; };
struct snd_soc_jack { unsigned int status, reports; } jack;
struct regmap { unsigned int values[65536], baseline[65536]; } map;
struct reg_sequence { unsigned int reg, def, delay; };
typedef int irqreturn_t;
static void *system_wq;
static unsigned int calls, fail_call, writes, reports;
static bool fail_after, stuck, feature = true, allocation_fail;
static int property_count = 7, irq_fail = -1, request_fail = -1, action_fail;
static int irq_depth[2], request_count;
static irqreturn_t (*handlers[2])(int, void *);
static void *handler_data[2], *allocation;
static void (*cleanup_action)(void *);
static void *cleanup_data;
static unsigned int properties[7] = {0x500, 0x500, 1, 0x1f0, 0x800, 0x800, 0x20};
static void mutex_init(struct mutex *m) { m->held = 0; }
static void mutex_lock(struct mutex *m) { assert(!m->held); m->held = 1; }
static void mutex_unlock(struct mutex *m) { assert(m->held); m->held = 0; }
static void disable_irq_nosync(int irq) { assert(irq == 10 || irq == 11); ++irq_depth[irq-10]; }
static void disable_irq(int irq) { disable_irq_nosync(irq); }
static void enable_irq(int irq) { assert(irq_depth[irq-10] > 0); --irq_depth[irq-10]; }
#define INIT_DELAYED_WORK(w, callback) do { (w)->fn = (callback); (w)->pending = false; } while (0)
static int mod_delayed_work(void *wq, struct delayed_work *w, unsigned int delay) {
 (void)wq; w->pending = true; w->delay = delay; return 0;
}
static void cancel_delayed_work_sync(struct delayed_work *w) { w->pending = false; }
static void cancel_delayed_work(struct delayed_work *w) { w->pending = false; }
static bool io_error(void) { return ++calls == fail_call; }
static bool writable(unsigned int reg) {
 return reg == 0x0246 || reg == 0x02a8 || reg == 0x0d1c || reg == 0x0d1e ||
        (reg >= 0x0f46 && reg <= 0x0f68 && reg % 2 == 0 && reg != 0x0f62);
}
static int regmap_read(struct regmap *m, unsigned int reg, unsigned int *value) {
 assert(reg < 65536 && !(reg & 1)); bool error = io_error();
 if (error && !fail_after) return -EIO;
 *value = m->values[reg]; return error ? -EIO : 0;
}
static int regmap_write(struct regmap *m, unsigned int reg, unsigned int value) {
 assert(writable(reg)); bool error = io_error();
 if (error && !fail_after) return -EIO;
 ++writes;
 if (reg == 0x0f5e) {
  assert(!(value & ~(0x8000 | 0x100 | 0x400)));
  unsigned int pending = m->values[reg] & 5;
  if (!stuck) {
   if (value & 0x100) pending &= ~1;
   if (value & 0x400) pending &= ~4;
  }
  m->values[reg] = pending | value;
 } else if (!(m->values[0x02a8] & 0x10) || reg < 0x0f46 || reg > 0x0f68) {
  m->values[reg] = value;
 }
 return error ? -EIO : 0;
}
static int regmap_update_bits(struct regmap *m, unsigned int reg, unsigned int mask, unsigned int value) {
 unsigned int old; int ret = regmap_read(m, reg, &old); if (ret) return ret;
 value = (old & ~mask) | (value & mask);
 return value == old ? 0 : regmap_write(m, reg, value);
}
static int regmap_multi_reg_write(struct regmap *m, const struct reg_sequence *s, unsigned int n) {
 for (unsigned int i = 0; i < n; ++i) { int ret = regmap_write(m, s[i].reg, s[i].def); if (ret) return ret; }
 return 0;
}
#define regmap_read_poll_timeout(m,reg,value,cond,interval,timeout) ({ \
 int result = -ETIMEDOUT; \
 assert((interval) == 100 && (timeout) == 5000); \
 for (unsigned int iteration = 0; iteration < 51; ++iteration) { \
  int r = regmap_read((m),(reg),&(value)); \
  if (r) { result = r; break; } \
  if (cond) { result = 0; break; } \
 } result; })
static bool device_property_read_bool(struct device *d, const char *name) {
 (void)d; assert(!strcmp(name, "mediatek,jack-detection")); return feature;
}
static int device_property_count_u32(struct device *d, const char *name) {
 (void)d; assert(!strcmp(name, "mediatek,accdet-pwm-settings")); return property_count;
}
static int device_property_read_u32_array(struct device *d, const char *name, unsigned int *s, size_t n) {
 (void)d; assert(!strcmp(name, "mediatek,accdet-pwm-settings") && n == 7);
 memcpy(s, properties, sizeof(properties)); return 0;
}
static void *devm_kzalloc(struct device *d, size_t n, int flags) {
 (void)d; (void)flags; if (allocation_fail) return NULL;
 assert(!allocation); return allocation = calloc(1,n);
}
static int platform_get_irq_byname(struct platform_device *p, const char *name) {
 (void)p; int n = !strcmp(name, "accdet") ? 0 : 1;
 assert(n == 0 || !strcmp(name, "accdet-eint"));
 return irq_fail == n ? -EPROBE_DEFER : 10+n;
}
static int devm_request_threaded_irq(struct device *d, int irq, void *top,
 irqreturn_t (*fn)(int,void *), unsigned long flags, const char *name, void *data) {
 (void)d; (void)name; assert(!top && flags == (IRQF_ONESHOT | IRQF_NO_AUTOEN));
 int n = irq-10; if (request_fail == n) return -EBUSY;
 handlers[n] = fn; handler_data[n] = data; irq_depth[n] = 1; ++request_count; return 0;
}
static int devm_add_action_or_reset(struct device *d, void (*fn)(void *), void *data) {
 (void)d; if (action_fail) { fn(data); return -ENOMEM; }
 cleanup_action = fn; cleanup_data = data; return 0;
}
static void snd_soc_jack_report(struct snd_soc_jack *j, unsigned int status, unsigned int mask);
'''
suffix = r'''
static struct mt6351_accdet *active;
static void snd_soc_jack_report(struct snd_soc_jack *j, unsigned int status, unsigned int mask) {
 assert(j && !active->lock.held); assert(mask == 3);
 j->status = (j->status & ~mask) | (status & mask); ++j->reports; ++reports;
}
static void reset(void) {
 free(allocation); allocation = NULL; active = NULL;
 memset(&map, 0, sizeof(map)); memset(&jack, 0, sizeof(jack));
 memset(irq_depth, 0, sizeof(irq_depth));
 calls = fail_call = writes = reports = 0; jiffies = 1000; fail_after = stuck = false;
 feature = true; allocation_fail = false; property_count = 7;
 irq_fail = request_fail = -1; action_fail = request_count = 0;
 cleanup_action = NULL; cleanup_data = NULL;
 // Shared clock, DCC contact-switch and unrelated analog bits are sentinels.
 map.values[0x0246] = 0x3270;
 map.values[0x02a8] = 0x6400;
 map.values[0x0d1c] = 0x1f04;
 map.values[0x0d1e] = 0x6000;
 map.values[0x0f46] = 0x10;
 map.values[0x0f64] = 0x61;
 map.values[0x0f6a] = 0x700; // debounced mechanical input is high: unplugged
 memcpy(map.baseline, map.values, sizeof(map.values));
}
static struct mt6351_accdet *probe(void) {
 active = mt6351_accdet_probe(&pdev, &map); assert(active && !IS_ERR(active));
 assert(calls == 0 && writes == 0 && irq_depth[0] == 1 && irq_depth[1] == 1);
 return active;
}
static void run_work(void) {
 assert(active->work.pending); jiffies += active->work.delay; active->work.pending = false; active->work.fn(&active->work.work);
}
static void start(void) {
 probe(); assert(mt6351_accdet_set_jack(active, &jack) == 0);
 assert(active->enabled && active->work.pending && active->work.delay == 300);
 assert(irq_depth[0] == 0 && irq_depth[1] == 0);
 assert(map.values[0x0f4c] == 0x4ff && map.values[0x0f4e] == 0x4ff);
 assert(map.values[0x0f50] == 0x81f0 && map.values[0x0f52] == 0x800);
 assert(map.values[0x0f54] == 0x800 && map.values[0x0f58] == 0x20);
 assert(map.values[0x0f64] == 0x461 && map.values[0x0f48] == 4);
 assert(map.values[0x0d1c] == 0x1ff4 && map.values[0x0d1e] == 0x680f);
}
static void stop(void) {
 assert(mt6351_accdet_set_jack(active, NULL) == 0);
 assert(!active->enabled && !active->jack && !active->work.pending && !active->bias_off_work.pending);
 assert(irq_depth[0] == 1 && irq_depth[1] == 1);
 assert(jack.status == 0);
 for (unsigned int i = 0; i < ARRAY_SIZE(mt6351_accdet_registers); ++i) {
  unsigned int reg = mt6351_accdet_registers[i].reg;
  unsigned int mask = mt6351_accdet_registers[i].mask;
  assert((map.values[reg] & mask) == (map.baseline[reg] & mask));
 }
 assert(!(map.values[0x0f5e] & 0x500));
 assert((map.values[0x0246] & ~0x200) == (map.baseline[0x0246] & ~0x200));
 assert((map.values[0x0d1c] & ~0xf0) == (map.baseline[0x0d1c] & ~0xf0));
}
static void signal_irq(bool present, unsigned int ab, unsigned int pending) {
 map.values[0x0f6a] = present ? 0 : 0x700;
 map.values[0x0f62] = ab << 6;
 map.values[0x0f5e] |= pending;
 assert(!irq_depth[0] && !irq_depth[1]);
 handlers[pending & 4 ? 1 : 0](pending & 4 ? 11 : 10, active);
}
int main(void) {
 // Independent checks from the MT6351 vendor register definitions, including
 // the missing CON18 number: CON19 is 0xf6a, not the linear 0xf6c guess.
 assert(ACCDET_RESET == 0x2a8 && ACCDET_EINT_STATE == 0xf6a);
 assert(ACCDET_EINT_MEM == (1u << 10));
 reset(); feature = false; assert(!mt6351_accdet_probe(&pdev, &map)); assert(!allocation && !writes);
 reset(); allocation_fail = true; assert(PTR_ERR(mt6351_accdet_probe(&pdev, &map)) == -ENOMEM);
 for (int n = -1; n <= 8; ++n) if (n != 7) {
  reset(); property_count = n; assert(IS_ERR(mt6351_accdet_probe(&pdev, &map))); assert(!writes);
 }
 for (int n = 0; n < 7; ++n) {
  reset(); unsigned int old = properties[n]; properties[n] = 65536;
  assert(IS_ERR(mt6351_accdet_probe(&pdev, &map))); assert(!writes); properties[n] = old;
 }
 for (int n = 0; n < 2; ++n) {
  reset(); irq_fail = n; assert(PTR_ERR(mt6351_accdet_probe(&pdev, &map)) == -EPROBE_DEFER); assert(!writes);
  reset(); request_fail = n; assert(PTR_ERR(mt6351_accdet_probe(&pdev, &map)) == -EBUSY); assert(!writes);
 }
 reset(); action_fail = 1; assert(PTR_ERR(mt6351_accdet_probe(&pdev, &map)) == -ENOMEM); assert(!writes);
 reset(); start(); unsigned int start_calls = calls; run_work(); assert(jack.reports == 1 && !jack.status); stop();
 // All start I/O failures, including writes that take effect then fail, unwind.
 for (unsigned int after = 0; after <= 1; ++after) for (unsigned int n = 1; n <= start_calls; ++n) {
  reset(); probe(); fail_call = n; fail_after = after;
  assert(mt6351_accdet_set_jack(active, &jack) == -EIO);
  assert(!active->enabled && !active->jack && irq_depth[0] == 1 && irq_depth[1] == 1);
  for (unsigned int i = 0; i < ARRAY_SIZE(mt6351_accdet_registers); ++i) {
   unsigned int reg = mt6351_accdet_registers[i].reg, mask = mt6351_accdet_registers[i].mask;
   if ((map.values[reg] & mask) != (map.baseline[reg] & mask)) {
    fprintf(stderr,"rollback mismatch call=%u after=%u reg=%x got=%x original=%x\n",n,after,reg,map.values[reg],map.baseline[reg]); abort();
   }
  }
 }
 for (unsigned int busy = 1; busy <= 16; busy <<= 1) {
  reset(); probe(); map.values[0x0f48] = busy; assert(mt6351_accdet_set_jack(active,&jack) == -EBUSY); assert(!writes);
 }
 reset(); probe(); map.values[0x02a8] |= 16; assert(mt6351_accdet_set_jack(active,&jack) == -EBUSY); assert(!writes);
 // Boot with a plug inserted, without relying on an interrupt edge.
 reset(); map.values[0x0f6a] = 0; map.values[0x0f62] = 1 << 6; start();
 run_work(); assert(active->present && active->work.pending && active->work.delay == 100);
 run_work(); assert(jack.status == 3); stop();
 // TRS, headset, button pull-down, invalid AB and a coalesced remove/insert.
 reset(); start(); run_work(); signal_irq(true,0,4); run_work(); assert(jack.status == 1); run_work();
 signal_irq(true,1,1); run_work(); assert(jack.status == 3);
 signal_irq(true,0,1); run_work(); assert(jack.status == 3);
 signal_irq(true,2,1); run_work(); assert(jack.status == 3);
 signal_irq(true,3,1); run_work(); assert(jack.status == 3);
 signal_irq(false,3,5); run_work(); assert(jack.status == 0 && !active->present);
 assert(!(map.values[0x0f5e] & 0x8505));
 for (int n = 0; n < 100; ++n) {
  signal_irq(true,1,4); signal_irq(false,3,4); run_work(); assert(!jack.status && !active->present);
 }
 // Capture closes while detection remains enabled; DCC contact bits survive.
 assert(mt6351_accdet_micbias(active,true) == 0); assert((map.values[0x0d1c] & 0xf0) == 0x70);
 assert(mt6351_accdet_micbias(active,false) == 0); assert((map.values[0x0d1c] & 0xf0) == 0xf0);
 assert((map.values[0x0d1c] & ~0xf0) == (map.baseline[0x0d1c] & ~0xf0)); stop();
 // Detector removal while headset capture still owns bias.
 reset(); start(); assert(mt6351_accdet_micbias(active,true) == 0);
 assert(mt6351_accdet_set_jack(active,NULL) == 0); assert((map.values[0x0d1c] & 0xf0) == 0x70);
 assert(mt6351_accdet_micbias(active,false) == 0); assert(!(map.values[0x0d1c] & 0xf0));
 // Runtime errors mask IRQs exactly once; explicit stop/start recovers depth.
 reset(); start(); run_work(); fail_call = calls + 1; signal_irq(true,1,4);
 assert(active->fault && irq_depth[0] == 1 && irq_depth[1] == 1);
 stop(); assert(mt6351_accdet_set_jack(active,&jack) == 0); assert(!active->fault && !irq_depth[0] && !irq_depth[1]); stop();
 reset(); start(); fail_call = calls + 1; run_work(); assert(active->fault); stop();
 // Every insertion I/O failure fences the detector, including changed writes.
 reset(); start(); run_work(); unsigned int before_irq = calls; signal_irq(true,1,4);
 unsigned int irq_calls = calls - before_irq;
 for (unsigned int after = 0; after < 2; ++after) for (unsigned int n = 1; n <= irq_calls; ++n) {
  reset(); start(); run_work(); fail_call = calls + n; fail_after = after; signal_irq(true,1,4);
  assert(active->fault && irq_depth[0] == 1 && irq_depth[1] == 1); stop();
 }
 // TRS bias timeout, headset retention and stale timer after rapid reinsertion.
 reset(); start(); run_work(); signal_irq(true,0,4); run_work(); run_work();
 assert(jack.status == 1 && active->bias_off_work.pending);
 jiffies = active->bias_off_at; active->bias_off_work.pending = false;
 active->bias_off_work.fn(&active->bias_off_work.work);
 assert(map.values[0x0f48] == 4 && map.values[0x0f4a] == 8 && jack.status == 1);
 signal_irq(false,3,4); run_work(); signal_irq(true,1,4); run_work(); run_work();
 jiffies = active->bias_off_at; active->bias_off_work.pending = false;
 active->bias_off_work.fn(&active->bias_off_work.work);
 assert(map.values[0x0f48] == 5 && map.values[0x0f4a] == 0x7f && jack.status == 3);
 signal_irq(false,3,4); run_work(); signal_irq(true,0,4); run_work(); run_work();
 unsigned long new_deadline = active->bias_off_at;
 active->bias_off_work.pending = false; active->bias_off_work.fn(&active->bias_off_work.work);
 assert(active->bias_off_work.pending && active->bias_off_work.delay == new_deadline - jiffies);
 assert(map.values[0x0f48] == 5); stop();
 // A stuck IRQ clear is bounded; stopping still deasserts clear commands.
 reset(); start(); run_work(); stuck = true; signal_irq(true,1,4);
 assert(active->fault && calls < 250);
 assert(mt6351_accdet_set_jack(active,NULL) == -ETIMEDOUT);
 assert(!(map.values[0x0f5e] & 0x500) && !active->enabled && irq_depth[0] == 1 && irq_depth[1] == 1);
 free(allocation); allocation = NULL;
 puts("PASS production detector: exact register map, probe gates, every start I/O failure, boot-time plug, IRQ/classification transitions, button type retention, bias coexistence, bounded IRQ fault and teardown");
}
'''
with tempfile.TemporaryDirectory(prefix='gemini-jack-') as temp:
    c = Path(temp) / 'jack.c'
    c.write_text(prefix + src + suffix)
    binary = Path(temp) / 'jack'
    subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-Wall', '-Wextra',
                    '-Werror', '-Wno-unused-parameter', '-Wno-sign-compare',
                    '-Wno-missing-field-initializers', '-g', '-O1',
                    '-fsanitize=address,undefined', '-fno-pie', '-no-pie',
                    str(c), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
