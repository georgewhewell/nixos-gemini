#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

enum { BUFFERS = 3, WIDTH = 1088, HEIGHT = 2160 };

static bool driver_is(int fd, const char *expected)
{
    drmVersionPtr version = drmGetVersion(fd);
    if (!version)
        return false;
    bool match = version->name && version->name_len == (int)strlen(expected) &&
                 !memcmp(version->name, expected, strlen(expected));
    drmFreeVersion(version);
    return match;
}

int main(int argc, char **argv)
{
    struct drm_mode_create_dumb buffers[BUFFERS] = {0};
    uint32_t imported[BUFFERS] = {0};
    int kms = -1, gpu = -1, dma = -1, result = 1;
    const char *stage = "arguments";
    uint64_t bytes = 0;
    setvbuf(stdout, NULL, _IOLBF, 0);
    alarm(15);
    if (argc != 3)
        goto out;
    stage = "open-kms";
    kms = open(argv[1], O_RDWR | O_CLOEXEC);
    if (kms < 0)
        goto out;
    stage = "open-gpu";
    gpu = open(argv[2], O_RDWR | O_CLOEXEC);
    if (gpu < 0)
        goto out;
    stage = "driver-identity";
    if (!driver_is(kms, "mediatek") || !driver_is(gpu, "panfrost"))
        goto out;
    for (unsigned i = 0; i < BUFFERS; ++i) {
        buffers[i].width = WIDTH;
        buffers[i].height = HEIGHT;
        buffers[i].bpp = 32;
        stage = "create-dumb";
        if (drmIoctl(kms, DRM_IOCTL_MODE_CREATE_DUMB, &buffers[i]))
            goto out;
        stage = "pitch-and-size";
        if (buffers[i].pitch < WIDTH * 4 || buffers[i].pitch % 64 ||
            buffers[i].size < (uint64_t)buffers[i].pitch * HEIGHT)
            goto out;
        stage = "prime-export";
        if (drmPrimeHandleToFD(kms, buffers[i].handle, DRM_CLOEXEC | DRM_RDWR, &dma))
            goto out;
        stage = "prime-import-panfrost";
        if (drmPrimeFDToHandle(gpu, dma, &imported[i]))
            goto out;
        close(dma);
        dma = -1;
        bytes += buffers[i].size;
        printf("buffer=%u size=%" PRIu64 " pitch=%u exported=yes imported=panfrost\n",
               i + 1, (uint64_t)buffers[i].size, buffers[i].pitch);
    }
    result = 0;
out:
    if (result)
        fprintf(stderr, "desktop-buffers: failed=%s errno=%d (%s)\n", stage, errno, strerror(errno));
    if (dma >= 0)
        close(dma);
    for (unsigned i = 0; i < BUFFERS; ++i) {
        if (imported[i]) {
            struct drm_gem_close close_buffer = { .handle = imported[i] };
            if (drmIoctl(gpu, DRM_IOCTL_GEM_CLOSE, &close_buffer))
                result = 1;
        }
        if (buffers[i].handle) {
            struct drm_mode_destroy_dumb destroy = { .handle = buffers[i].handle };
            if (drmIoctl(kms, DRM_IOCTL_MODE_DESTROY_DUMB, &destroy))
                result = 1;
        }
    }
    if (gpu >= 0)
        close(gpu);
    if (kms >= 0)
        close(kms);
    alarm(0);
    if (!result)
        printf("desktop-buffers=passed concurrent=%u bytes=%" PRIu64 " handles=released\n", BUFFERS, bytes);
    return result;
}
