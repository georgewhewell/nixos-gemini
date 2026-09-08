#!/usr/bin/env python3
"""Execute the renderer's actual pixel validation without an EGL/GPU device."""
import os
from pathlib import Path
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
print('PASS: actual red/green full pixel checks; sentinel/last-alpha/blue faults reject with one diagnostic')
