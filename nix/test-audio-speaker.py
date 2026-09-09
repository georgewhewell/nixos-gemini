#!/usr/bin/env python3
"""Check the production speaker event against the vendor pulse protocol."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

kernel = Path(sys.argv[1]).resolve()
source = (kernel / 'sound/soc/mediatek/mt6797/mt6797-mt6351.c').read_text()
event = source[source.index('static void gemini_speaker_disable('):
               source.index('static int gemini_late_probe(')]
definitions = '\n'.join(line for line in source.splitlines() if line.startswith('#define GEMINI_SPEAKER_')) + '\n'
prefix = r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#define SND_SOC_DAPM_POST_PMU 1
#define SND_SOC_DAPM_PRE_PMD 2
struct gpio_desc { int pin, level; } gpios[2] = {{0, 0}, {1, 0}};
struct mt6797_mt6351_priv { struct gpio_desc *speaker_enable[2]; } test_priv = {{&gpios[0], &gpios[1]}};
struct snd_soc_card { void *dev; } test_card;
struct snd_soc_dapm_widget { void *dapm; } widget;
struct snd_kcontrol { int unused; };
#define snd_soc_dapm_to_card(dapm) (&test_card)
#define snd_soc_card_get_drvdata(card) (&test_priv)
#define dev_info(dev, ...) ((void)(dev))
struct operation { char type; int a, b; } operations[100];
static int count, irq, fail_pin = -1, fail_value;
static void record(char type, int a, int b) {
 assert(count < 100); operations[count++] = (struct operation){type, a, b};
}
static void gpiod_set_value(struct gpio_desc *gpio, int value) {
 record('G', gpio->pin, value); gpio->level = value;
}
static int gpiod_get_value(struct gpio_desc *gpio) {
 assert(!irq); record('R', gpio->pin, 0);
 return gpio->pin == fail_pin ? fail_value : gpio->level;
}
static void usleep_range(int min, int max) { assert(!irq); record('S', min, max); }
static void msleep(int ms) { assert(!irq); record('M', ms, 0); }
static void udelay(int us) { assert(irq); record('U', us, 0); }
#define local_irq_save(flags) do { assert(!irq); (flags) = 0; irq = 1; record('I', 1, 0); } while (0)
#define local_irq_restore(flags) do { assert(irq && !(flags)); irq = 0; record('I', 0, 0); } while (0)
'''
suffix = r'''
static int pos;
static void expect(char type, int a, int b) {
 assert(pos < count);
 struct operation op = operations[pos++];
 assert(op.type == type && op.a == a && op.b == b);
}
static void expect_off(void) {
 expect('G', 0, 0); expect('G', 1, 0);
 assert(pos < count && operations[pos].type == 'S');
 assert(operations[pos].a >= 500 && operations[pos].b >= operations[pos].a);
 ++pos;
}
static void reset(void) { count = pos = 0; assert(!irq); fail_pin = -1; }
int main(void) {
 assert(gemini_speaker_event(&widget, NULL, SND_SOC_DAPM_POST_PMU) == 0);
 expect_off();
 assert(operations[pos].type == 'S' && operations[pos].a >= 1000 && operations[pos].b <= 20000); ++pos;
 expect('I', 1, 0);
 for (int pin = 0; pin < 2; ++pin)
  for (int pulse = 0; pulse < 3; ++pulse) {
   expect('G', pin, 0); expect('U', 2, 0);
   expect('G', pin, 1); expect('U', 2, 0);
  }
 expect('I', 0, 0); expect('M', 25, 0);
 expect('R', 0, 0); expect('R', 1, 0); assert(pos == count);
 assert(gpios[0].level == 1 && gpios[1].level == 1);
 reset();
 assert(gemini_speaker_event(&widget, NULL, SND_SOC_DAPM_PRE_PMD) == 0);
 expect_off(); expect('R', 0, 0); expect('R', 1, 0); assert(pos == count);
 for (int event = 1; event <= 2; ++event)
  for (int pin = 0; pin < 2; ++pin)
   for (int negative = 0; negative <= 1; ++negative) {
    reset(); fail_pin = pin; fail_value = negative ? -ENODEV : event == 2;
    assert(gemini_speaker_event(&widget, NULL, event) == (negative ? -ENODEV : -EIO));
    assert(gpios[0].level == 0 && gpios[1].level == 0);
    pos = count - 3; expect_off(); assert(pos == count);
   }
 reset(); assert(gemini_speaker_event(&widget, NULL, 99) == -EINVAL); assert(count == 0);
 gpios[0].level = gpios[1].level = 1;
 gemini_speaker_disable(&test_priv); expect_off(); assert(pos == count);
 assert(!gpios[0].level && !gpios[1].level);
 puts("PASS actual speaker event: vendor mode-3 pulses, reset/warmup/shutdown, IRQ boundaries, both readback failures and cleanup");
}
'''
with tempfile.TemporaryDirectory(prefix='gemini-speaker-') as temp:
    path = Path(temp)
    c = path / 'event.c'
    c.write_text(definitions + prefix + event + suffix)
    binary = path / 'event'
    subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-Wall', '-Wextra',
                    '-Werror', '-Wno-unused-parameter', '-g', '-O1',
                    '-fsanitize=address,undefined', '-fno-pie', '-no-pie',
                    str(c), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
