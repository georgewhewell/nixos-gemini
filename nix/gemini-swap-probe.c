#define _GNU_SOURCE
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#define BYTES (128U * 1024U * 1024U)
#define MIN_KIB (64U * 1024U)

static uint64_t next(uint64_t x) {
    x ^= x << 13; x ^= x >> 7; x ^= x << 17; return x;
}

static void fill(volatile uint64_t *data, size_t words) {
    uint64_t x = UINT64_C(0x3fbea45106d9c827);
    for (size_t i = 0; i < words; i++) { x = next(x); data[i] = x; }
}

static int verify(volatile uint64_t *data, size_t words) {
    uint64_t x = UINT64_C(0x3fbea45106d9c827);
    for (size_t i = 0; i < words; i++) {
        x = next(x);
        if (data[i] != x) return 0;
    }
    return 1;
}

static int stats(uint64_t *read_sectors, uint64_t *write_sectors) {
    FILE *f = fopen("/sys/class/block/mmcblk0p34/stat", "r");
    uint64_t fields[7];
    if (!f) return 0;
    for (size_t i = 0; i < 7; i++) {
        if (fscanf(f, "%" SCNu64, &fields[i]) != 1) { fclose(f); return 0; }
    }
    fclose(f); *read_sectors = fields[2]; *write_sectors = fields[6]; return 1;
}

static uint64_t swapped_kib(void) {
    FILE *f = fopen("/proc/self/status", "r");
    char line[256]; uint64_t value = UINT64_MAX;
    if (!f) return value;
    while (fgets(line, sizeof(line), f)) {
        if (sscanf(line, "VmSwap: %" SCNu64 " kB", &value) == 1) break;
    }
    fclose(f); return value;
}

static int qualified_swap(void) {
    FILE *f = fopen("/proc/swaps", "r");
    char line[512], device[128], type[32]; uint64_t size, used; int priority;
    if (!f) return 0;
    int ok = fgets(line, sizeof(line), f) != NULL && fgets(line, sizeof(line), f) != NULL;
    if (ok) ok = sscanf(line, "%127s %31s %" SCNu64 " %" SCNu64 " %d", device, type, &size, &used, &priority) == 5;
    if (ok) ok = !strcmp(device, "/dev/mmcblk0p34") && !strcmp(type, "partition") && size == 5242876;
    if (ok) ok = fgets(line, sizeof(line), f) == NULL;
    fclose(f); return ok;
}

int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "--self-test")) {
        volatile uint64_t data[1024]; fill(data, 1024);
        if (!verify(data, 1024)) return 1;
        data[1023] ^= 1;
        if (verify(data, 1024)) return 1;
        puts("pattern self-test passed"); return 0;
    }
    if (argc != 1 || geteuid() != 0 || sysconf(_SC_PAGESIZE) != 4096 || !qualified_swap()) {
        fputs("Requires root, 4 KiB pages and the exact active Gemini p34 swap\n", stderr); return 2;
    }
    uint64_t read_before, write_before, read_after, write_after;
    if (!stats(&read_before, &write_before)) return 2;
    volatile uint64_t *data = mmap(NULL, BYTES, PROT_READ | PROT_WRITE,
                                 MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (data == MAP_FAILED) { perror("mmap"); return 1; }
    fill(data, BYTES / sizeof(uint64_t));
    if (madvise((void *)data, BYTES, MADV_PAGEOUT)) { perror("MADV_PAGEOUT"); return 1; }
    uint64_t swapped = 0;
    const struct timespec delay = { .tv_sec = 0, .tv_nsec = 100000000 };
    for (unsigned i = 0; i < 600; i++) {
        swapped = swapped_kib();
        if (swapped == UINT64_MAX) return 1;
        if (swapped >= MIN_KIB) break;
        nanosleep(&delay, NULL);
    }
    if (swapped < MIN_KIB) { fputs("Insufficient page-out evidence\n", stderr); return 1; }
    if (!verify(data, BYTES / sizeof(uint64_t))) { fputs("Paging changed data bytes\n", stderr); return 1; }
    if (!stats(&read_after, &write_after) || read_after < read_before || write_after < write_before ||
        read_after - read_before < MIN_KIB * 2 || write_after - write_before < MIN_KIB * 2) {
        fputs("Insufficient p34 backing-device read/write evidence\n", stderr); return 1;
    }
    printf("{\"bytes\":%u,\"swapped_kib\":%" PRIu64 ",\"read_sectors\":%" PRIu64
           ",\"written_sectors\":%" PRIu64 ",\"pattern_verified\":true}\n",
           BYTES, swapped, read_after - read_before, write_after - write_before);
    if (munmap((void *)data, BYTES)) return 1;
    return 0;
}
