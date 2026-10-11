#!/usr/bin/env python3
"""Own a bounded media observation and supervised return to the accepted image.

The external-module observer runs separately in the existing observation
window. Reuse the common boot, storage, paging and recovery owner without
repeating unchanged RTC diagnostics or promoting a temporary module trial.
"""
import importlib.util
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('media_boot', root/'tools/test-boot.py')
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)
p = boot.p
p.ENTRYPOINT = Path(__file__).resolve()
p.EXTRA_EXECUTED_SOURCES += ('tools/test-media-boot.py', 'tools/qualify-vdec-irq.py')
p.EXTRA_EXECUTED_SOURCES += tuple('research/'+name for name in (
    'mt6797-vdec-v4l2/Kbuild', 'mt6797-vdec-v4l2/v4l2.c',
    'mt6797-vdec-v4l2/engine.c', 'mt6797-vdec-v4l2/engine.h',
    'mt6797-vdec-v4l2/controls.c', 'mt6797-vdec-v4l2/request-test.c',
    'mt6797-vdec/mt6797-h264-controls.c', 'mt6797-vdec/mt6797-h264-controls.h',
    'mt6797-vdec/pcm64-fixture.h', 'mt6797-vdec/compare-frame.py'))
p.preflight = boot.base_preflight
p.finish = boot.base_finish

def configure(*args, **kwargs):
    runner = boot.base_configure(*args, **kwargs)
    runner.CANDIDATE_DESKTOP = 'gnome'
    runner.backend.MTK = runner.backend.MTK_RTC
    return runner

p.configure = configure
if __name__ == '__main__':
    if '--keep' in sys.argv:
        sys.exit('External media observations always return to the accepted image')
    try:
        p.main(boot.artifacts)
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
