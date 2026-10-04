#define _GNU_SOURCE
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <wayland-client.h>
#include <xkbcommon/xkbcommon.h>
#include <xkbcommon/xkbcommon-compose.h>
#include "reference.h"

static void fail(const char *stage)
{
    fprintf(stderr, "desktop-keyboard: failed=%s\n", stage);
    exit(1);
}

static struct xkb_state *new_state(struct xkb_keymap *map)
{
    struct xkb_state *state = xkb_state_new(map);
    if (!state) fail("state-allocation");
    return state;
}

static void press(struct xkb_state *state, unsigned int code, bool down)
{
    xkb_state_update_key(state, code + 8, down ? XKB_KEY_DOWN : XKB_KEY_UP);
}

static void check_map(struct xkb_keymap *map)
{
    const char *layout = xkb_keymap_layout_get_name(map, 0);
    if (xkb_keymap_num_layouts(map) != 1 || !layout ||
        strcmp(layout, "Gemini English (US)"))
        fail("layout-name");
    xkb_mod_index_t shift = xkb_keymap_mod_get_index(map, XKB_MOD_NAME_SHIFT);
    xkb_mod_index_t fn = xkb_keymap_mod_get_index(map, "Mod5");
    xkb_mod_index_t caps = xkb_keymap_mod_get_index(map, XKB_MOD_NAME_CAPS);
    if (shift >= 32 || fn >= 32 || caps >= 32) fail("modifier-indices");
    struct xkb_state *state = new_state(map);
    unsigned int checked = 0;
    for (size_t i = 0; i < sizeof(reference) / sizeof(reference[0]); i++) {
        for (unsigned int level = 0; level < 8; level++) {
            xkb_state_update_mask(state, ((level & 1) ? 1U << shift : 0) |
                                  ((level & 2) ? 1U << fn : 0), 0,
                                  (level & 4) ? 1U << caps : 0, 0, 0, 0);
            xkb_keysym_t got = xkb_state_key_get_one_sym(state, reference[i].code + 8);
            if (got != reference[i].sym[level]) {
                fprintf(stderr, "code=%u level=%u actual=0x%x expected=0x%x\n",
                        reference[i].code, level, got, reference[i].sym[level]);
                fail("keysym-mismatch");
            }
            checked++;
        }
    }
    xkb_state_unref(state);
    /* Exercise physical modifier key transitions, independently of mask tests. */
    const struct { unsigned int code; const char *mod; } modifiers[] = {
        {42, XKB_MOD_NAME_SHIFT}, {54, XKB_MOD_NAME_SHIFT},
        {29, XKB_MOD_NAME_CTRL}, {56, XKB_MOD_NAME_ALT}, {125, "Mod5"},
    };
    for (size_t i = 0; i < sizeof(modifiers) / sizeof(modifiers[0]); i++) {
        state = new_state(map);
        press(state, modifiers[i].code, true);
        if (xkb_state_mod_name_is_active(state, modifiers[i].mod, XKB_STATE_MODS_EFFECTIVE) != 1)
            fail("modifier-press");
        if (modifiers[i].code == 125 &&
            xkb_state_mod_name_is_active(state, "Mod4", XKB_STATE_MODS_EFFECTIVE) != 0)
            fail("fn-is-logo");
        press(state, modifiers[i].code, false);
        if (xkb_state_mod_name_is_active(state, modifiers[i].mod, XKB_STATE_MODS_EFFECTIVE) != 0)
            fail("modifier-release");
        xkb_state_unref(state);
    }
    state = new_state(map);
    for (int enabled = 1; enabled >= 0; enabled--) {
        press(state, 125, true);
        press(state, 15, true);
        press(state, 15, false);
        press(state, 125, false);
        if (xkb_state_mod_name_is_active(state, XKB_MOD_NAME_CAPS, XKB_STATE_MODS_LOCKED) != (int)enabled)
            fail("fn-tab-caps-toggle");
    }
    xkb_state_unref(state);
    printf("keymap=gemian-us-v1 combinations=%u modifiers=5 caps-toggle=passed\n", checked);

    /* Match Weston's client locale lookup and compose actual mapped accents. */
    const char *locale = getenv("LC_ALL");
    if (!locale) locale = getenv("LC_CTYPE");
    if (!locale) locale = getenv("LANG");
    if (!locale) locale = "C";
    struct xkb_context *context = xkb_context_new(XKB_CONTEXT_NO_DEFAULT_INCLUDES);
    if (!context) fail("compose-context");
    struct xkb_compose_table *table = xkb_compose_table_new_from_locale(context, locale,
        XKB_COMPOSE_COMPILE_NO_FLAGS);
    if (!table) fail("compose-table");
    struct xkb_compose_state *compose = xkb_compose_state_new(table, XKB_COMPOSE_STATE_NO_FLAGS);
    if (!compose) fail("compose-state");
    const struct { unsigned int code, unicode; } accents[] = {
        {40, 0xe9}, {50, 0xe8}, {52, 0x1ebd}, {35, 0xeb},
        {36, 0xea}, {38, 0x11b}, {44, 0x1eb9}, {45, 0x117},
    };
    state = new_state(map);
    for (size_t i = 0; i < sizeof(accents) / sizeof(accents[0]); i++) {
        xkb_state_update_mask(state, (1U << shift) | (1U << fn), 0, 0, 0, 0, 0);
        xkb_keysym_t dead = xkb_state_key_get_one_sym(state, accents[i].code + 8);
        xkb_state_update_mask(state, 0, 0, 0, 0, 0, 0);
        xkb_keysym_t base = xkb_state_key_get_one_sym(state, 18 + 8); /* E */
        xkb_compose_state_reset(compose);
        if (xkb_compose_state_feed(compose, dead) != XKB_COMPOSE_FEED_ACCEPTED ||
            xkb_compose_state_get_status(compose) != XKB_COMPOSE_COMPOSING ||
            xkb_compose_state_feed(compose, base) != XKB_COMPOSE_FEED_ACCEPTED ||
            xkb_compose_state_get_status(compose) != XKB_COMPOSE_COMPOSED ||
            xkb_keysym_to_utf32(xkb_compose_state_get_one_sym(compose)) != accents[i].unicode)
            fail("dead-accent-compose");
    }
    xkb_state_unref(state);
    xkb_compose_state_unref(compose);
    xkb_compose_table_unref(table);
    xkb_context_unref(context);
    printf("compose=passed accents=8 locale=%s\n", locale);
}

struct check {
    struct wl_seat *seat;
    struct wl_keyboard *keyboard;
    unsigned int seats, maps;
    bool fixture;
    char name[128];
};

static void keymap(void *data, struct wl_keyboard *keyboard, uint32_t format, int fd, uint32_t size)
{
    struct check *c = data;
    struct stat st;
    if (format != WL_KEYBOARD_KEYMAP_FORMAT_XKB_V1 || size < 2 || size > 1024 * 1024 ||
        fstat(fd, &st) || st.st_size < size) fail("keymap-file");
    char *text = mmap(NULL, size, PROT_READ, MAP_PRIVATE, fd, 0);
    close(fd);
    if (text == MAP_FAILED || text[size - 1]) fail("keymap-mapping");
    struct xkb_context *context = xkb_context_new(XKB_CONTEXT_NO_DEFAULT_INCLUDES);
    if (!context) fail("context-allocation");
    struct xkb_keymap *map = xkb_keymap_new_from_string(context, text,
        XKB_KEYMAP_FORMAT_TEXT_V1, XKB_KEYMAP_COMPILE_NO_FLAGS);
    munmap(text, size);
    if (!map) fail("keymap-compile");
    check_map(map);
    xkb_keymap_unref(map);
    xkb_context_unref(context);
    c->maps++;
}
static void enter(void *d, struct wl_keyboard *k, uint32_t s, struct wl_surface *w, struct wl_array *a) { }
static void leave(void *d, struct wl_keyboard *k, uint32_t s, struct wl_surface *w) { }
static void key(void *d, struct wl_keyboard *k, uint32_t s, uint32_t t, uint32_t key, uint32_t state) { }
static void mods(void *d, struct wl_keyboard *k, uint32_t s, uint32_t a, uint32_t b, uint32_t c, uint32_t g) { }
static void repeat(void *d, struct wl_keyboard *k, int32_t rate, int32_t delay) { }
static const struct wl_keyboard_listener keyboard_listener = {
    .keymap = keymap, .enter = enter, .leave = leave, .key = key,
    .modifiers = mods, .repeat_info = repeat,
};
static void capabilities(void *data, struct wl_seat *seat, uint32_t caps)
{
    struct check *c = data;
    if ((caps & WL_SEAT_CAPABILITY_KEYBOARD) && !c->keyboard) {
        c->keyboard = wl_seat_get_keyboard(seat);
        wl_keyboard_add_listener(c->keyboard, &keyboard_listener, c);
    }
}
static void seat_name(void *data, struct wl_seat *seat, const char *name)
{
    snprintf(((struct check *)data)->name, sizeof(((struct check *)data)->name), "%s", name);
}
static const struct wl_seat_listener seat_listener = { .capabilities = capabilities, .name = seat_name };
static void global(void *data, struct wl_registry *registry, uint32_t name, const char *interface, uint32_t version)
{
    struct check *c = data;
    if (!strcmp(interface, "wl_seat")) {
        if (++c->seats != 1 || version < 2) fail("seat-count-or-version");
        c->seat = wl_registry_bind(registry, name, &wl_seat_interface, version < 5 ? version : 5);
        wl_seat_add_listener(c->seat, &seat_listener, c);
    }
}
static void removed(void *data, struct wl_registry *registry, uint32_t name) { fail("global-removed"); }
static const struct wl_registry_listener registry_listener = { .global = global, .global_remove = removed };

int main(int argc, char **argv)
{
    struct check c = { 0 };
    if (argc == 2 && !strcmp(argv[1], "--headless-fixture")) c.fixture = true;
    else if (argc != 1) fail("arguments");
    alarm(10);
    struct wl_display *display = wl_display_connect(NULL);
    if (!display) fail("connect");
    struct wl_registry *registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &registry_listener, &c);
    for (unsigned int i = 0; i < 3; i++)
        if (wl_display_roundtrip(display) < 0) fail("roundtrip");
    if (c.seats != 1 || !c.keyboard || c.maps != 1 || !c.name[0]) fail("keyboard-keymap-missing");
    if (c.fixture != !strcmp(c.name, "gemini-keymap-fixture")) fail("fixture-mode");
    printf("desktop-keyboard=passed mode=%s seat=%s physical-key-press=unobserved\n",
           c.fixture ? "headless-fixture" : "device", c.name);
    wl_keyboard_destroy(c.keyboard);
    wl_seat_destroy(c.seat);
    wl_registry_destroy(registry);
    wl_display_disconnect(display);
    return 0;
}
