#!/usr/bin/env python3
"""Exercise actual renderer admission/validation helpers without EGL or a GPU."""
from fractions import Fraction
import os
from pathlib import Path
import re
import subprocess
import tempfile

source = Path(__file__).with_name('gpu-render-smoke.c').read_text()
start = source.index('\t\tfor (unsigned int i = 0; i < sizeof(pixels); i += 4)')
end = source.index('\n\t\tprintf("draw=', start)
check = source[start:end]
assert 'memset(pixels, 0xa5, sizeof(pixels));' in source
code = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static void fail(const char *step) { (void)step; exit(3); }
int main(int argc, char **argv) {
    if (argc != 3) return 9;
    int pass = atoi(argv[1]), mutation = atoi(argv[2]);
    unsigned char pixels[64 * 64 * 4];
    for (unsigned int i = 0; i < sizeof(pixels); i += 4) {
        pixels[i] = pass == 0 ? 255 : 0;
        pixels[i+1] = pass == 1 ? 255 : 0;
        pixels[i+2] = 0; pixels[i+3] = 255;
    }
    if (mutation == 1) memset(pixels, 0xa5, sizeof(pixels));
    if (mutation == 2) pixels[sizeof(pixels)-1] = 0;
    if (mutation == 3) pixels[2] = 255;
''' + check + '\nreturn 0;\n}\n'


def function(name):
    """Extract one production helper, including nested initializer braces."""
    match = re.search(r'^static\b[^\n]+\b' + re.escape(name) + r'\(', source, re.M)
    assert match, name
    opening = source.index('{', match.end())
    depth = 0
    for position in range(opening, len(source)):
        depth += (source[position] == '{') - (source[position] == '}')
        if not depth:
            return source[match.start():position + 1]
    raise AssertionError(f'unclosed helper {name}')


# Public EGL extension tokens and Linux DRM fourcc/modifier values. The host
# fixture needs no graphics development package or substitute rendering path.
egl_tokens = {
    'EGL_FALSE': 0, 'EGL_TRUE': 1, 'EGL_NONE': 0x3038,
    'EGL_WIDTH': 0x3057, 'EGL_HEIGHT': 0x3056,
    'EGL_LINUX_DRM_FOURCC_EXT': 0x3271,
    'EGL_DMA_BUF_PLANE0_FD_EXT': 0x3272,
    'EGL_DMA_BUF_PLANE0_OFFSET_EXT': 0x3273,
    'EGL_DMA_BUF_PLANE0_PITCH_EXT': 0x3274,
    'EGL_DMA_BUF_PLANE1_FD_EXT': 0x3275,
    'EGL_DMA_BUF_PLANE1_OFFSET_EXT': 0x3276,
    'EGL_DMA_BUF_PLANE1_PITCH_EXT': 0x3277,
    'EGL_YUV_COLOR_SPACE_HINT_EXT': 0x327B,
    'EGL_SAMPLE_RANGE_HINT_EXT': 0x327C,
    'EGL_YUV_CHROMA_HORIZONTAL_SITING_HINT_EXT': 0x327D,
    'EGL_YUV_CHROMA_VERTICAL_SITING_HINT_EXT': 0x327E,
    'EGL_ITU_REC601_EXT': 0x327F, 'EGL_YUV_NARROW_RANGE_EXT': 0x3283,
    'EGL_YUV_CHROMA_SITING_0_EXT': 0x3284,
    'EGL_DMA_BUF_PLANE0_MODIFIER_LO_EXT': 0x3443,
    'EGL_DMA_BUF_PLANE0_MODIFIER_HI_EXT': 0x3444,
    'EGL_DMA_BUF_PLANE1_MODIFIER_LO_EXT': 0x3445,
    'EGL_DMA_BUF_PLANE1_MODIFIER_HI_EXT': 0x3446,
}
definitions = '\n'.join(line for line in source.splitlines()
                        if line.startswith('#define MM21_'))
definitions += '\n' + '\n'.join(f'#define {name} {value}'
                                for name, value in egl_tokens.items())
native_code = r'''
#include <limits.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef int EGLint;
typedef unsigned int EGLBoolean;
typedef unsigned long long EGLuint64KHR;
#define DRM_FORMAT_NV12 0x3231564e
#define DRM_FORMAT_MOD_MTK_16L_32S_TILE 0x0b00000000000001ULL
static void fail(const char *step) { (void)step; exit(3); }
''' + definitions + '\n' + '\n'.join(function(name) for name in (
    'parse_fd', 'native_mm21_args', 'has_extension', 'native_mm21_attributes',
    'native_mm21_modifier', 'native_mm21_expected', 'check_native_mm21_pixels',
)) + r'''
int main(int argc, char **argv) {
    if (argc < 2) return 9;
    if (!strcmp(argv[1], "fd") && argc == 3) {
        int fd = 123;
        bool valid = parse_fd(!strcmp(argv[2], "~NULL~") ? NULL : argv[2], &fd);
        printf("%u %d\n", valid, fd);
    } else if (!strcmp(argv[1], "args") && argc == 6) {
        char *test[] = {"gpu-render-smoke", "renderD128", argv[3], argv[4], argv[5], NULL};
        int fds[2] = {-1, -1};
        printf("%u\n", native_mm21_args(atoi(argv[2]), test, fds));
    } else if (!strcmp(argv[1], "extension") && argc == 4) {
        printf("%u\n", has_extension(!strcmp(argv[2], "~NULL~") ? NULL : argv[2],
                                     !strcmp(argv[3], "~NULL~") ? NULL : argv[3]));
    } else if (!strcmp(argv[1], "attributes") && argc == 2) {
        EGLint attributes[MM21_ATTRIBUTE_COUNT];
        const int fds[] = {37, 71};
        native_mm21_attributes(attributes, fds);
        for (unsigned int i = 0; i < MM21_ATTRIBUTE_COUNT; i++)
            printf("%s%d", i ? " " : "", attributes[i]);
        putchar('\n');
    } else if (!strcmp(argv[1], "modifier") && argc == 4) {
        printf("%u\n", native_mm21_modifier(strtoull(argv[2], NULL, 0),
                                            strtoul(argv[3], NULL, 0)));
    } else if (!strcmp(argv[1], "oracle") && argc == 2) {
        for (unsigned int y = 0; y < MM21_HEIGHT; y++)
            for (unsigned int x = 0; x < MM21_WIDTH; x++) {
                unsigned char rgba[4];
                native_mm21_expected(x, y, rgba);
                if (fwrite(rgba, sizeof(rgba), 1, stdout) != 1) return 9;
            }
    } else if (!strcmp(argv[1], "pixels") && argc == 3) {
        unsigned char pixels[MM21_LUMA * 4];
        FILE *input = fopen(argv[2], "rb");
        if (!input || fread(pixels, sizeof(pixels), 1, input) != 1 ||
            fgetc(input) != EOF || fclose(input)) return 9;
        check_native_mm21_pixels(pixels);
    } else return 9;
    return 0;
}
'''


def reference_rgb(y, u, v):
    """Independent exact-rational BT.601 oracle, without tiled input addressing."""
    kr, kb = Fraction(299, 1000), Fraction(114, 1000)
    kg = 1 - kr - kb
    luma = Fraction((y - 16) * 255, 219)
    red = luma + (2 - 2 * kr) * Fraction((v - 128) * 255, 224)
    blue = luma + (2 - 2 * kb) * Fraction((u - 128) * 255, 224)
    green = (luma - kr * red - kb * blue) / kg
    return bytes(int(max(0, min(255, component)) + Fraction(1, 2))
                 for component in (red, green, blue)) + b'\xff'


palette = [reference_rgb(*color) for color in (
    (81, 90, 240), (145, 54, 34), (41, 240, 110), (128, 128, 128),
)]
assert palette == [bytes(color) for color in (
    (254, 0, 0, 255), (0, 255, 1, 255), (0, 0, 255, 255), (130, 130, 130, 255),
)]
reference = b''.join(palette[(x // 8 + 3 * (y // 8)) % 4]
                     for y in range(64) for x in range(80))

with tempfile.TemporaryDirectory(prefix='gemini-pixel-check-') as directory:
    root = Path(directory)
    (root / 'check.c').write_text(code)
    exe = root / 'check'
    subprocess.run([os.environ.get('HOSTCC', 'cc'), '-Wall', '-Wextra', '-Werror',
                    str(root / 'check.c'), '-o', str(exe)], check=True)
    for draw in range(2):
        for mutation in range(4):
            result = subprocess.run([str(exe), str(draw), str(mutation)],
                                    capture_output=True, text=True)
            assert result.returncode == (3 if mutation else 0), result
            if mutation:
                assert result.stderr.count('pixel_mismatch ') == 1
                pixel = 4095 if mutation == 2 else 0
                assert f'draw={draw} pixel={pixel} ' in result.stderr

    (root / 'native.c').write_text(native_code)
    native = root / 'native'
    subprocess.run([os.environ.get('HOSTCC', 'cc'), '-std=gnu11', '-Wall', '-Wextra',
                    '-Werror', str(root / 'native.c'), '-o', str(native)], check=True)

    def invoke(*arguments):
        return subprocess.run([str(native), *map(str, arguments)],
                              capture_output=True, check=True).stdout

    # Failed fd parses leave the caller's output untouched; native CLI rejects
    # duplicate descriptors, invalid selectors and every incomplete arity.
    for text, expected in [('3', 3), ('71', 71), ('0003', 3), ('2147483647', 2147483647)]:
        assert invoke('fd', text) == f'1 {expected}\n'.encode(), text
    for text in ('~NULL~', '', '0', '1', '2', '-3', '+3', ' 3', '3 ', '3x',
                 '2147483648', '999999999999999999999999999999'):
        assert invoke('fd', text) == b'0 123\n', text
    assert invoke('args', 5, '--native-mm21', '3', '4') == b'1\n'
    for count in (0, 1, 2, 3, 4, 6, 7):
        assert invoke('args', count, '--native-mm21', '3', '4') == b'0\n'
    for selector, left, right in (
        ('--other', '3', '4'), ('--native-mm21x', '3', '4'),
        ('--native-mm21', '3', '3'), ('--native-mm21', '3', '0003'),
        ('--native-mm21', '2', '4'), ('--native-mm21', '3', '2147483648'),
    ):
        assert invoke('args', 5, selector, left, right) == b'0\n'

    name = 'EGL_EXT_image_dma_buf_import'
    for extensions in (name, f'{name} EGL_OTHER', f'EGL_OTHER {name}',
                       f' EGL_OTHER  {name}  '):
        assert invoke('extension', extensions, name) == b'1\n'
    for extensions, wanted in (
        ('~NULL~', name), ('', name), (name, ''), (name, '~NULL~'),
        (name + '_modifiers', name), ('prefix_' + name, name),
        (name + '_modifiers ' + name, name + ' '), (name, 'EGL_OTHER'),
    ):
        assert invoke('extension', extensions, wanted) == b'0\n'

    attributes = list(map(int, invoke('attributes').split()))
    assert len(attributes) == 35 and attributes[-1] == egl_tokens['EGL_NONE']
    keys = attributes[:-1:2]
    assert len(keys) == len(set(keys)) == 17
    assert dict(zip(keys, attributes[1::2])) == {
        0x3057: 80, 0x3056: 64, 0x3271: 0x3231564E,
        0x3272: 37, 0x3273: 0, 0x3274: 80, 0x3443: 1, 0x3444: 0x0B000000,
        0x3275: 71, 0x3276: 5120, 0x3277: 80, 0x3445: 1, 0x3446: 0x0B000000,
        0x327B: 0x327F, 0x327C: 0x3283, 0x327D: 0x3284, 0x327E: 0x3284,
    }
    for external in (0, 1):
        assert invoke('modifier', '0x0b00000000000001', external) == b'1\n'
    for modifier, external in (('0x0b00000000000001', 2), ('0', 0),
                               ('0x0800000000000001', 1)):
        assert invoke('modifier', modifier, external) == b'0\n'
    assert invoke('oracle') == reference

    tolerance = bytearray(reference)
    for index in range(len(tolerance)):
        if index % 4 != 3:
            tolerance[index] += 2 if tolerance[index] <= 253 else -2
    outside = bytearray(reference)
    outside[24 * 4] += 3
    alpha = bytearray(reference)
    alpha[-1] = 254
    swapped = bytearray(reference)
    for index in range(0, len(swapped), 4):
        swapped[index], swapped[index + 2] = swapped[index + 2], swapped[index]
    flipped = b''.join(reference[y * 320:(y + 1) * 320] for y in reversed(range(64)))
    cases = (
        ('exact', reference, None), ('rgb-tolerance-two', tolerance, None),
        ('rgb-tolerance-three', outside, (24, 0)), ('last-alpha', alpha, (79, 63)),
        ('sentinel', b'\xa5' * len(reference), (0, 0)),
        ('swapped-red-blue', swapped, (0, 0)), ('upside-down', flipped, (0, 0)),
    )
    for name, pixels, mismatch in cases:
        fixture = root / f'{name}.rgba'
        fixture.write_bytes(pixels)
        result = subprocess.run([str(native), 'pixels', str(fixture)], capture_output=True)
        assert result.returncode == (3 if mismatch else 0), (name, result)
        if mismatch:
            assert result.stderr.count(b'native_pixel_mismatch ') == 1, (name, result)
            x, y = mismatch
            assert f'x={x} y={y} '.encode() in result.stderr, (name, result)
            assert len(result.stderr) < 200, (name, result)
print('PASS: actual red/green full pixel checks; sentinel/last-alpha/blue faults reject with one diagnostic')
print('PASS: native fd/CLI/extension/modifier admission; exact public import attributes; '
      'independent601 oracle; full native pixel/tolerance/alpha/orientation checks')
