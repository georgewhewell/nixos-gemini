#define _GNU_SOURCE
#include <errno.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <wayland-client.h>
#include "xdg-shell-client-protocol.h"
#include "presentation-time-client-protocol.h"

enum { WIDTH = 320, HEIGHT = 160, FRAMES = 3 };
struct check {
	struct wl_display *display;
	struct wl_compositor *compositor;
	struct wl_shm *shm;
	struct wl_seat *seat;
	struct wl_output *output;
	struct xdg_wm_base *wm;
	struct wp_presentation *presentation;
	struct wl_surface *surface;
	struct xdg_surface *xdg_surface;
	struct xdg_toplevel *toplevel;
	struct wl_buffer *buffers[FRAMES];
	uint32_t input, frames, clock_id;
	uint64_t last_timestamp, last_sequence;
	int width, height, scale, transform;
	bool configured, fixture;
	char output_name[128];
};

static void fail(const char *stage)
{
	fprintf(stderr, "desktop-presentation: failed=%s\n", stage);
	exit(1);
}

static void draw(struct check *c);

static void feedback_output(void *data, struct wp_presentation_feedback *feedback,
			    struct wl_output *output)
{
	struct check *c = data;
	if (output != c->output)
		fail("unexpected-presentation-output");
}

static void feedback_presented(void *data, struct wp_presentation_feedback *feedback,
	uint32_t sec_hi, uint32_t sec_lo, uint32_t nsec, uint32_t refresh,
	uint32_t seq_hi, uint32_t seq_lo, uint32_t flags)
{
	struct check *c = data;
	uint64_t seconds = ((uint64_t)sec_hi << 32) | sec_lo;
	uint64_t timestamp = seconds * UINT64_C(1000000000) + nsec;
	uint64_t sequence = ((uint64_t)seq_hi << 32) | seq_lo;
	if (nsec >= 1000000000 || !timestamp || !refresh ||
	    (c->frames && timestamp <= c->last_timestamp))
		fail("invalid-presentation-time");
	if (!c->fixture && (!(flags & WP_PRESENTATION_FEEDBACK_KIND_VSYNC) ||
	    (c->frames && sequence <= c->last_sequence)))
		fail("missing-vsync-progress");
	c->last_timestamp = timestamp;
	c->last_sequence = sequence;
	++c->frames;
	printf("presented=%u timestamp_ns=%" PRIu64 " refresh_ns=%u sequence=%" PRIu64 " flags=0x%x\n",
	       c->frames, timestamp, refresh, sequence, flags);
	wp_presentation_feedback_destroy(feedback);
	if (c->frames < FRAMES)
		draw(c);
}

static void feedback_discarded(void *data, struct wp_presentation_feedback *feedback)
{
	fail("frame-discarded");
}

static const struct wp_presentation_feedback_listener feedback_listener = {
	.sync_output = feedback_output,
	.presented = feedback_presented,
	.discarded = feedback_discarded,
};

static void draw(struct check *c)
{
	struct wp_presentation_feedback *f =
		wp_presentation_feedback(c->presentation, c->surface);
	wp_presentation_feedback_add_listener(f, &feedback_listener, c);
	wl_surface_attach(c->surface, c->buffers[c->frames], 0, 0);
	wl_surface_damage(c->surface, 0, 0, WIDTH, HEIGHT);
	wl_surface_commit(c->surface);
}

static void surface_configure(void *data, struct xdg_surface *surface, uint32_t serial)
{
	struct check *c = data;
	xdg_surface_ack_configure(surface, serial);
	if (!c->configured) {
		c->configured = true;
		draw(c);
	}
}
static const struct xdg_surface_listener surface_listener = { .configure = surface_configure };
static void toplevel_configure(void *data, struct xdg_toplevel *toplevel,
	int32_t width, int32_t height, struct wl_array *states) { }
static void toplevel_close(void *data, struct xdg_toplevel *toplevel) { fail("window-closed"); }
static const struct xdg_toplevel_listener toplevel_listener = {
	.configure = toplevel_configure, .close = toplevel_close,
};
static void wm_ping(void *data, struct xdg_wm_base *wm, uint32_t serial)
{ xdg_wm_base_pong(wm, serial); }
static const struct xdg_wm_base_listener wm_listener = { .ping = wm_ping };
static void presentation_clock(void *data, struct wp_presentation *p, uint32_t clock_id)
{ ((struct check *)data)->clock_id = clock_id; }
static const struct wp_presentation_listener presentation_listener = { .clock_id = presentation_clock };
static void seat_capabilities(void *data, struct wl_seat *seat, uint32_t capabilities)
{ ((struct check *)data)->input = capabilities; }
static void seat_name(void *data, struct wl_seat *seat, const char *name) { }
static const struct wl_seat_listener seat_listener = {
	.capabilities = seat_capabilities, .name = seat_name,
};
static void output_geometry(void *data, struct wl_output *output, int32_t x, int32_t y,
	int32_t pw, int32_t ph, int32_t subpixel, const char *make, const char *model, int32_t transform)
{ ((struct check *)data)->transform = transform; }
static void output_mode(void *data, struct wl_output *output, uint32_t flags,
	int32_t width, int32_t height, int32_t refresh)
{
	struct check *c = data;
	if (flags & WL_OUTPUT_MODE_CURRENT) { c->width = width; c->height = height; }
}
static void output_done(void *data, struct wl_output *output) { }
static void output_scale(void *data, struct wl_output *output, int32_t scale)
{ ((struct check *)data)->scale = scale; }
static void output_name(void *data, struct wl_output *output, const char *name)
{ snprintf(((struct check *)data)->output_name, 128, "%s", name); }
static void output_description(void *data, struct wl_output *output, const char *description) { }
static const struct wl_output_listener output_listener = {
	.geometry = output_geometry, .mode = output_mode, .done = output_done,
	.scale = output_scale, .name = output_name, .description = output_description,
};

static void registry_global(void *data, struct wl_registry *registry, uint32_t name,
	const char *interface, uint32_t version)
{
	struct check *c = data;
	if (!strcmp(interface, "wl_compositor"))
		c->compositor = wl_registry_bind(registry, name, &wl_compositor_interface, 1);
	else if (!strcmp(interface, "wl_shm"))
		c->shm = wl_registry_bind(registry, name, &wl_shm_interface, 1);
	else if (!strcmp(interface, "xdg_wm_base")) {
		c->wm = wl_registry_bind(registry, name, &xdg_wm_base_interface, 1);
		xdg_wm_base_add_listener(c->wm, &wm_listener, c);
	} else if (!strcmp(interface, "wp_presentation")) {
		c->presentation = wl_registry_bind(registry, name, &wp_presentation_interface, 1);
		wp_presentation_add_listener(c->presentation, &presentation_listener, c);
	} else if (!strcmp(interface, "wl_seat") && !c->seat) {
		c->seat = wl_registry_bind(registry, name, &wl_seat_interface, version < 2 ? version : 2);
		wl_seat_add_listener(c->seat, &seat_listener, c);
	} else if (!strcmp(interface, "wl_output") && !c->output) {
		if (version < 4) fail("output-version");
		c->output = wl_registry_bind(registry, name, &wl_output_interface, 4);
		wl_output_add_listener(c->output, &output_listener, c);
	}
}
static void registry_remove(void *data, struct wl_registry *registry, uint32_t name)
{ fail("global-removed-during-check"); }
static const struct wl_registry_listener registry_listener = {
	.global = registry_global, .global_remove = registry_remove,
};

int main(int argc, char **argv)
{
	struct check c = { .clock_id = UINT32_MAX };
	if (argc == 2 && !strcmp(argv[1], "--headless-fixture")) c.fixture = true;
	else if (argc != 1) fail("arguments");
	/* Bounds even a compositor that accepts the socket but never dispatches. */
	alarm(15);
	setvbuf(stdout, NULL, _IOLBF, 0);
	c.display = wl_display_connect(NULL);
	if (!c.display) fail("connect");
	struct wl_registry *registry = wl_display_get_registry(c.display);
	wl_registry_add_listener(registry, &registry_listener, &c);
	if (wl_display_roundtrip(c.display) < 0 || wl_display_roundtrip(c.display) < 0)
		fail("registry-roundtrip");
	if (!c.compositor || !c.shm || !c.wm || !c.presentation || !c.output ||
	    c.clock_id == UINT32_MAX) fail("required-protocols");
	if (c.width != 1080 || c.height != 2160 || c.scale != 2 ||
	    c.transform != WL_OUTPUT_TRANSFORM_90) fail("output-geometry");
	if (!c.fixture && (strcmp(c.output_name, "DSI-1") ||
	    (c.input & (WL_SEAT_CAPABILITY_KEYBOARD | WL_SEAT_CAPABILITY_TOUCH)) !=
	    (WL_SEAT_CAPABILITY_KEYBOARD | WL_SEAT_CAPABILITY_TOUCH)))
		fail("physical-output-or-input-capabilities");
	printf("output=%s mode=%dx%d scale=%d transform=%d input=0x%x clock=%u\n",
	       c.output_name, c.width, c.height, c.scale, c.transform, c.input, c.clock_id);
	size_t frame_size = WIDTH * HEIGHT * sizeof(uint32_t);
	size_t pool_size = frame_size * FRAMES;
	int fd = memfd_create("gemini-display-check", MFD_CLOEXEC);
	if (fd < 0 || ftruncate(fd, pool_size)) fail("shm-file");
	uint32_t *pixels = mmap(NULL, pool_size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
	if (pixels == MAP_FAILED) fail("shm-map");
	struct wl_shm_pool *pool = wl_shm_create_pool(c.shm, fd, pool_size);
	static const uint32_t colors[] = { 0xff175d8a, 0xff34804a, 0xff925833 };
	for (unsigned int frame = 0; frame < FRAMES; ++frame) {
		for (unsigned int y = 0; y < HEIGHT; ++y)
			for (unsigned int x = 0; x < WIDTH; ++x)
				pixels[frame * WIDTH * HEIGHT + y * WIDTH + x] =
					((x / 20 + y / 20) & 1) ? colors[frame] : 0xffeeeeee;
		c.buffers[frame] = wl_shm_pool_create_buffer(pool, frame * frame_size,
			WIDTH, HEIGHT, WIDTH * sizeof(uint32_t), WL_SHM_FORMAT_XRGB8888);
	}
	wl_shm_pool_destroy(pool);
	close(fd);
	c.surface = wl_compositor_create_surface(c.compositor);
	c.xdg_surface = xdg_wm_base_get_xdg_surface(c.wm, c.surface);
	xdg_surface_add_listener(c.xdg_surface, &surface_listener, &c);
	c.toplevel = xdg_surface_get_toplevel(c.xdg_surface);
	xdg_toplevel_add_listener(c.toplevel, &toplevel_listener, &c);
	xdg_toplevel_set_title(c.toplevel, "Gemini display check");
	xdg_toplevel_set_app_id(c.toplevel, "gemini-display-check");
	xdg_toplevel_set_min_size(c.toplevel, WIDTH, HEIGHT);
	xdg_toplevel_set_max_size(c.toplevel, WIDTH, HEIGHT);
	wl_surface_commit(c.surface);
	while (c.frames < FRAMES)
		if (wl_display_dispatch(c.display) < 0) fail("dispatch");
	xdg_toplevel_destroy(c.toplevel);
	xdg_surface_destroy(c.xdg_surface);
	wl_surface_destroy(c.surface);
	for (unsigned int i = 0; i < FRAMES; ++i) wl_buffer_destroy(c.buffers[i]);
	munmap(pixels, pool_size);
	if (wl_display_roundtrip(c.display) < 0) fail("cleanup-roundtrip");
	wl_display_disconnect(c.display);
	alarm(0);
	printf("desktop-presentation=passed mode=%s frames=%u\n",
	       c.fixture ? "headless-fixture" : "device", c.frames);
	return 0;
}
