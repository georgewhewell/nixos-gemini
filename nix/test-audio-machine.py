#!/usr/bin/env python3
"""Exercise the actual machine probe with the kernel's current DAI macros.

Host adapters replace allocation, GPIO, OF and card registration. They do not
replace the probe, card/link declarations or COMP_DUMMY expansion.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

kernel = Path(sys.argv[1]).resolve()
source = Path(sys.argv[2]) if len(sys.argv) > 2 else kernel / 'sound/soc/mediatek/mt6797/mt6797-mt6351.c'
s = source.read_text()
header = (kernel / 'include/sound/soc.h').read_text()
def macro(name):
    lines = header.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith('#define ' + name + '('))
    end = start
    while lines[end].endswith('\\'):
        end += 1
    return '\n'.join(lines[start:end+1]) + '\n'
macros = ''.join(macro(name) for name in [
    'SND_SOC_DAILINK_REG1', 'SND_SOC_DAILINK_REG2', 'SND_SOC_DAILINK_REG3',
    'SND_SOC_DAILINK_REG', 'SND_SOC_DAILINK_DEF', 'SND_SOC_DAILINK_DEFS',
    'DAILINK_COMP_ARRAY', 'COMP_EMPTY', 'COMP_CPU', 'COMP_CODEC', 'COMP_DUMMY',
    'for_each_card_prelinks', 'for_each_link_platforms', 'for_each_link_codecs'])
declarations = s[s.index('SND_SOC_DAILINK_DEFS(playback_1,'):s.index('static int mt6797_mt6351_dev_probe(')]
probe = s[s.index('static int mt6797_mt6351_dev_probe('):s.index('\n#ifdef CONFIG_OF', s.index('static int mt6797_mt6351_dev_probe('))]
prefix = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define GFP_KERNEL 0
#define THIS_MODULE NULL
#define SND_SOC_DPCM_TRIGGER_PRE 0
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define CONCATENATE_(a,b) a##b
#define CONCATENATE(a,b) CONCATENATE_(a,b)
#define COUNT_ARGS_(_1,_2,_3,N,...) N
#define COUNT_ARGS(...) COUNT_ARGS_(__VA_ARGS__,3,2,1)
#define GPIOD_OUT_LOW 0
#define GEMINI_SPEAKER_AMPS 2
#define IS_ERR(p) ((uintptr_t)(p) > (uintptr_t)-4096)
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define EPROBE_DEFER 517
struct device_node { int id; } root, platform_node, codec_node;
struct device { struct device_node *of_node; };
struct platform_device { struct device dev; };
struct gpio_desc { int value; } gpio, speaker_gpios[2];
struct snd_soc_dai_link_component { const char *name; struct device_node *of_node; const char *dai_name; };
struct snd_soc_dai_link {
 const char *name, *stream_name;
 struct snd_soc_dai_link_component *cpus, *codecs, *platforms;
 unsigned num_cpus, num_codecs, num_platforms;
 int trigger[2], dynamic, playback_only, capture_only, ignore_suspend, no_pcm;
};
struct snd_soc_card {
 const char *name; void *owner; struct snd_soc_dai_link *dai_link; int num_links;
 struct device *dev; const void *dapm_widgets, *dapm_routes; unsigned num_dapm_widgets, num_dapm_routes;
 void *drvdata; const void *controls; unsigned num_controls; int (*late_probe)(struct snd_soc_card *); int (*remove)(struct snd_soc_card *);
};
struct mutex { int initialized; };
static void mutex_init(struct mutex *m) { m->initialized = 1; }
struct mt6797_mt6351_priv { struct snd_soc_card *card; struct mutex speaker_lock; struct gpio_desc *mic_enable; struct gpio_desc *speaker_enable[2]; };
static const int gemini_widgets[2], gemini_routes[4], gemini_controls[1];
static int gemini_late_probe(struct snd_soc_card *card) { (void)card; return 0; }
static int gemini_card_remove(struct snd_soc_card *card) { (void)card; return 0; }
static int allocation_count, fail_allocation, compatible, missing_platform, missing_codec;
static int gpio_error, action_error, register_error, registered_count, node_refs;
static int speaker_count = 2, speaker_error_pin = -1, speaker_sleep, speaker_low, action_count, fail_action;
static void *allocations[256]; static unsigned allocated;
static struct snd_soc_card *registered[4];
static void *devm_kmemdup(struct device *dev, const void *src, size_t size, int flags) {
 (void)dev; (void)flags;
 if (++allocation_count == fail_allocation) return NULL;
 if (!size) return (void *)16; /* the actual kernel's ZERO_SIZE_PTR */
 void *p = malloc(size); assert(p); memcpy(p, src, size);
 assert(allocated < ARRAY_SIZE(allocations)); allocations[allocated++] = p; return p;
}
static void *devm_kzalloc(struct device *dev, size_t size, int flags) {
 void *zero = calloc(1, size); assert(zero);
 void *p = devm_kmemdup(dev, zero, size, flags); free(zero); return p;
}
static int of_device_is_compatible(struct device_node *node, const char *name) {
 assert(node == &root); assert(!strcmp(name, "planet,gemini-mt6797-mt6351")); return compatible;
}
static struct gpio_desc *devm_gpiod_get(struct device *dev, const char *name, int flags) {
 (void)dev; assert(!strcmp(name, "microphone-enable")); assert(flags == GPIOD_OUT_LOW);
 gpio.value = 0; return gpio_error ? (void *)(intptr_t)gpio_error : &gpio;
}
static int gpiod_count(struct device *dev, const char *name) {
 (void)dev; assert(!strcmp(name, "speaker-enable")); return speaker_count;
}
static struct gpio_desc *devm_gpiod_get_index(struct device *dev, const char *name, int i, int flags) {
 (void)dev; assert(!strcmp(name, "speaker-enable") && i >= 0 && i < 2 && flags == GPIOD_OUT_LOW);
 speaker_gpios[i].value = 0;
 return i == speaker_error_pin ? (void *)(intptr_t)-EPROBE_DEFER : &speaker_gpios[i];
}
static int gpiod_cansleep(struct gpio_desc *gpio) { (void)gpio; return speaker_sleep; }
static int gpiod_is_active_low(struct gpio_desc *gpio) { (void)gpio; return speaker_low; }
static void gemini_speaker_disable(void *data) {
 struct mt6797_mt6351_priv *p = data; p->speaker_enable[0]->value = p->speaker_enable[1]->value = 0;
}
static void gemini_mic_disable(void *data) { ((struct mt6797_mt6351_priv *)data)->mic_enable->value = 0; }
static int devm_add_action_or_reset(struct device *dev, void (*fn)(void *), void *data) {
 (void)dev; ++action_count;
 int error = action_error || action_count == fail_action ? -ENOMEM : 0;
 if (error) fn(data);
 return error;
}
#define snd_soc_card_set_drvdata(card, data) ((card)->drvdata = (data))
#define dev_err_probe(dev, error, ...) (error)
#define dev_err(...) ((void)0)
static struct device_node *of_parse_phandle(struct device_node *node, const char *name, int index) {
 assert(node == &root && index == 0);
 if (!strcmp(name, "mediatek,platform")) { if (missing_platform) return NULL; ++node_refs; return &platform_node; }
 assert(!strcmp(name, "mediatek,audio-codec")); if (missing_codec) return NULL; ++node_refs; return &codec_node;
}
static void of_node_put(struct device_node *node) { assert(node == &platform_node || node == &codec_node); --node_refs; }
#define snd_soc_link_to_platform(link, i) (&(link)->platforms[i])
#define snd_soc_link_to_codec(link, i) (&(link)->codecs[i])
static int devm_snd_soc_register_card(struct device *dev, struct snd_soc_card *card) {
 assert(card->dev == dev); assert(card->num_links == 12);
 for (int i = 0; i < card->num_links; ++i) {
  struct snd_soc_dai_link *link = &card->dai_link[i];
  assert(link->num_cpus == 1 && link->cpus[0].dai_name);
  for (unsigned j = 0; j < link->num_platforms; ++j)
   assert(link->platforms[j].name || link->platforms[j].of_node == &platform_node);
  for (unsigned j = 0; j < link->num_codecs; ++j)
   assert(link->codecs[j].name || link->codecs[j].of_node == &codec_node);
  /* Empty frontend codecs reach ASoC untouched; the core installs its dummy. */
  assert(link->num_codecs == (unsigned)(i == 9));
 }
 if (compatible) assert(card->drvdata && card->num_dapm_widgets == 2 && card->num_dapm_routes == 4 && card->num_controls == 1 && card->late_probe == gemini_late_probe);
 else assert(!card->drvdata && !card->num_dapm_widgets && !card->num_dapm_routes);
 if (register_error) return register_error;
 assert(registered_count < 4); registered[registered_count++] = card; return 0;
}
'''
suffix = r'''
static void cleanup(void) {
 assert(node_refs == 0);
 for (unsigned i = 0; i < allocated; ++i) free(allocations[i]);
 allocated = 0; registered_count = 0; allocation_count = 0;
 fail_allocation = 0; gpio_error = 0; action_error = 0; register_error = 0;
 missing_platform = 0; missing_codec = 0;
 speaker_count = 2; speaker_error_pin = -1; speaker_sleep = speaker_low = action_count = fail_action = 0;
}
static void globals_unchanged(void) {
 assert(mt6797_mt6351_card.dev == NULL && mt6797_mt6351_card.drvdata == NULL);
 for (unsigned i = 0; i < ARRAY_SIZE(mt6797_mt6351_dai_links); ++i) {
  struct snd_soc_dai_link *link = &mt6797_mt6351_dai_links[i];
  for (unsigned j = 0; j < link->num_platforms; ++j) assert(link->platforms[j].of_node == NULL);
  for (unsigned j = 0; j < link->num_codecs; ++j) assert(link->codecs[j].of_node == NULL);
 }
}
int main(void) {
 struct platform_device pdev = { .dev.of_node = &root };
 for (compatible = 0; compatible <= 1; ++compatible) {
  assert(mt6797_mt6351_dev_probe(&pdev) == 0);
  int count = allocation_count;
  globals_unchanged();
  assert(mt6797_mt6351_dev_probe(&pdev) == 0);
  assert(registered[0] != registered[1]);
  assert(registered[0]->dai_link != registered[1]->dai_link);
  assert(registered[0]->dai_link[9].codecs != registered[1]->dai_link[9].codecs);
  globals_unchanged(); cleanup();
  for (int i = 1; i <= count; ++i) {
   fail_allocation = i; assert(mt6797_mt6351_dev_probe(&pdev) == -ENOMEM);
   assert(!registered_count); globals_unchanged(); cleanup();
  }
  missing_platform = 1; assert(mt6797_mt6351_dev_probe(&pdev) == -EINVAL); globals_unchanged(); cleanup();
  missing_codec = 1; assert(mt6797_mt6351_dev_probe(&pdev) == -EINVAL); globals_unchanged(); cleanup();
  register_error = -EIO; assert(mt6797_mt6351_dev_probe(&pdev) == -EIO); globals_unchanged(); cleanup();
 }
 compatible = 1;
 gpio_error = -EPROBE_DEFER; assert(mt6797_mt6351_dev_probe(&pdev) == -EPROBE_DEFER); cleanup();
 action_error = -ENOMEM; assert(mt6797_mt6351_dev_probe(&pdev) == -ENOMEM); cleanup();
 for (int i = 0; i < 2; ++i) {
  speaker_error_pin = i; assert(mt6797_mt6351_dev_probe(&pdev) == -EPROBE_DEFER); cleanup();
 }
 for (int i = -1; i < 4; ++i) {
  if (i == 2) continue;
  speaker_count = i; assert(mt6797_mt6351_dev_probe(&pdev) == (i < 0 ? i : -EINVAL)); cleanup();
 }
 speaker_sleep = 1; assert(mt6797_mt6351_dev_probe(&pdev) == -EINVAL); cleanup();
 speaker_low = 1; assert(mt6797_mt6351_dev_probe(&pdev) == -EINVAL); cleanup();
 fail_action = 2; assert(mt6797_mt6351_dev_probe(&pdev) == -ENOMEM); cleanup();
 /* Also exercise an absent platform array and explicit named components. */
 struct snd_soc_dai_link *link = &mt6797_mt6351_dai_links[0];
 struct snd_soc_dai_link_component *platform = link->platforms;
 link->num_platforms = 0; link->platforms = NULL;
 assert(mt6797_mt6351_dev_probe(&pdev) == 0); globals_unchanged(); cleanup();
 link->num_platforms = 1; link->platforms = platform;
 platform->name = "fixed-platform";
 mt6797_mt6351_dai_links[9].codecs[0].name = "fixed-codec";
 assert(mt6797_mt6351_dev_probe(&pdev) == 0);
 assert(registered[0]->dai_link[0].platforms[0].of_node == NULL);
 assert(registered[0]->dai_link[9].codecs[0].of_node == NULL);
 globals_unchanged(); cleanup();
 puts("PASS actual machine probe: empty dummy codecs/platforms, allocation failures, repeated cards, phandle/GPIO/registration failures and named components");
 return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='gemini-audio-machine-') as temp:
    path = Path(temp)
    c = path / 'probe.c'
    c.write_text(prefix + macros + declarations + probe + suffix)
    binary = path / 'probe'
    subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-sign-compare', '-g', '-O1', '-fsanitize=address,undefined', '-fno-pie', '-no-pie', str(c), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
