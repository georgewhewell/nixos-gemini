/* Host-only seat: Weston compiles its configured map, then sends wl_keyboard. */
#include <libweston/libweston.h>
#include <weston/weston.h>

/* Internal exported APIs from the pinned Weston 16 libweston-internal.h. */
void weston_seat_init(struct weston_seat *, struct weston_compositor *, const char *);
int weston_seat_init_keyboard(struct weston_seat *, struct xkb_keymap *);
void weston_seat_release(struct weston_seat *);

static struct weston_seat seat;
static struct wl_listener destroy;

static void finish(struct wl_listener *listener, void *data)
{
    wl_list_remove(&listener->link);
    weston_seat_release(&seat);
}

WL_EXPORT int wet_module_init(struct weston_compositor *compositor, int *argc, char *argv[])
{
    weston_seat_init(&seat, compositor, "gemini-keymap-fixture");
    if (weston_seat_init_keyboard(&seat, NULL) < 0) {
        weston_seat_release(&seat);
        return -1;
    }
    destroy.notify = finish;
    wl_signal_add(&compositor->destroy_signal, &destroy);
    return 0;
}
