#define _GNU_SOURCE
#include "touch_input.h"
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <linux/input.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>

/* Transport only. LVGL owns hit testing, recognizers, scrolling and animation.
 * Type B slots and single-touch ABS devices are supported. Unknown Type A
 * hardware is not silently interpreted as a working multitouch device. */
typedef struct {
  int fd, used, mt, slot, slots, xmin, xmax, ymin, ymax, dropped, suppress;
  int active[SOY_CONTACTS], was[SOY_CONTACTS], x[SOY_CONTACTS], y[SOY_CONTACTS];
  int virtual_device;
  dev_t dev;
  ino_t inode;
} Device;
static Device devices[8];
static unsigned long events, drops, sequence;
static int owner = -1;
static int sync_active(Device *d);
static int bit(const unsigned long *b, unsigned i) {
  return !!(b[i / (8 * sizeof(long))] & (1UL << (i % (8 * sizeof(long)))));
}
static int scaled(int x, int lo, int hi, int size) {
  int64_t v = ((int64_t)x - lo) * (size - 1) / ((int64_t)hi - lo);
  return v < 0 ? 0 : v >= size ? size - 1 : (int)v;
}
int soy_input_pollfds(struct pollfd *fds, int capacity) {
  int count = 0;
  for (int i = 0; i < 8 && count < capacity; i++)
    if (devices[i].used)
      fds[count++] = (struct pollfd){.fd = devices[i].fd, .events = POLLIN};
  return count;
}
void soy_input_scan(void) {
  glob_t g = {0};
  if (glob("/dev/input/event*", 0, NULL, &g)) {
    globfree(&g);
    return;
  }
  for (size_t n = 0; n < g.gl_pathc; n++) {
    struct stat st;
    if (stat(g.gl_pathv[n], &st))
      continue;
    int found = 0, free_slot = -1;
    for (int j = 0; j < 8; j++) {
      if (devices[j].used && devices[j].dev == st.st_rdev &&
          devices[j].inode == st.st_ino)
        found = 1;
      if (!devices[j].used)
        free_slot = j;
    }
    if (found || free_slot < 0)
      continue;
    int fd = open(g.gl_pathv[n], O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0)
      continue;
    unsigned long absbits[(ABS_MAX + 8 * sizeof(long)) / (8 * sizeof(long))] = {
        0};
    unsigned long props[2] = {0};
    struct input_absinfo ax, ay, slots;
    struct input_id id = {0};
    ioctl(fd, EVIOCGBIT(EV_ABS, sizeof absbits), absbits);
    ioctl(fd, EVIOCGPROP(sizeof props), props);
    ioctl(fd, EVIOCGID, &id);
    int mt = bit(absbits, ABS_MT_SLOT) && bit(absbits, ABS_MT_TRACKING_ID);
    int xc = mt ? ABS_MT_POSITION_X : ABS_X,
        yc = mt ? ABS_MT_POSITION_Y : ABS_Y;
    if (!bit(props, INPUT_PROP_DIRECT) || !bit(absbits, xc) ||
        !bit(absbits, yc) || ioctl(fd, EVIOCGABS(xc), &ax) ||
        ioctl(fd, EVIOCGABS(yc), &ay) || ax.maximum <= ax.minimum ||
        ay.maximum <= ay.minimum) {
      close(fd);
      continue;
    }
    int ns = 1;
    if (mt) {
      if (ioctl(fd, EVIOCGABS(ABS_MT_SLOT), &slots) || slots.minimum != 0 ||
          slots.maximum >= SOY_CONTACTS) {
        close(fd);
        continue;
      }
      ns = slots.maximum + 1;
    }
    Device *d = &devices[free_slot];
    *d = (Device){.fd = fd,
                  .used = 1,
                  .mt = mt,
                  .slots = ns,
                  .xmin = ax.minimum,
                  .xmax = ax.maximum,
                  .ymin = ay.minimum,
                  .ymax = ay.maximum,
                  .dev = st.st_rdev,
                  .inode = st.st_ino,
                  .virtual_device = id.bustype == BUS_VIRTUAL,
                  .suppress = 1};
    /* Opening midway through a contact is not a fresh tap. Query at the first
     * report and wait for all fingers to lift before accepting a new gesture.
     */
    if (sync_active(d)) {
      close(fd);
      d->used = 0;
      continue;
    }
    d->suppress = 0;
    for (int i = 0; i < d->slots; i++)
      if (d->active[i])
        d->suppress = 1;
    if (mt)
      d->slot = slots.value;
  }
  globfree(&g);
}
static int sync_active(Device *d) {
  memset(d->active, 0, sizeof d->active);
  memset(d->was, 0, sizeof d->was);
  if (d->mt) {
    int32_t v[SOY_CONTACTS + 1] = {ABS_MT_TRACKING_ID};
    if (ioctl(d->fd, EVIOCGMTSLOTS((d->slots + 1) * sizeof(int32_t)), v))
      return -1;
    for (int i = 0; i < d->slots; i++)
      d->active[i] = v[i + 1] >= 0;
  } else {
    unsigned long b[(KEY_MAX + 8 * sizeof(long)) / (8 * sizeof(long))] = {0};
    if (ioctl(d->fd, EVIOCGKEY(sizeof b), b))
      return -1;
    d->active[0] = bit(b, BTN_TOUCH);
  }
  return 0;
}
int soy_input_next(SoyContacts *f) {
  memset(f, 0, sizeof *f);
  for (int n = 0; n < 8; n++) {
    Device *d = &devices[n];
    if (!d->used)
      continue;
    struct input_event e;
    ssize_t got;
    /* Bounded: a broken device cannot starve rendering or the SSH control FIFO.
     */
    for (int budget = 0; budget < 256; budget++) {
      got = read(d->fd, &e, sizeof e);
      if (got != sizeof e) {
        if (got < 0 && (errno == EAGAIN || errno == EINTR))
          break;
        close(d->fd);
        d->used = 0;
        if (owner == n) {
          owner = -1;
          f->cancel = 1;
          f->sequence = ++sequence;
          return 1;
        }
        break;
      }
      events++;
      if (e.type == EV_SYN && e.code == SYN_DROPPED) {
        d->dropped = d->suppress = 1;
        drops++;
        if (owner == n) {
          owner = -1;
          f->cancel = 1;
          f->sequence = ++sequence;
          return 1;
        }
        continue;
      }
      if (e.type == EV_SYN && e.code == SYN_REPORT) {
        if (d->dropped) {
          d->dropped = 0;
          if (sync_active(d)) {
            close(d->fd);
            d->used = 0;
            break;
          }
        }
        int active = 0;
        for (int i = 0; i < d->slots; i++)
          active += d->active[i];
        if (d->suppress) {
          if (!active)
            d->suppress = 0;
          continue;
        }
        if (owner < 0 && active)
          owner = n;
        if (owner != n)
          continue;
        f->active = active;
        f->virtual_device = d->virtual_device;
        for (int i = 0; i < d->slots; i++) {
          if (d->active[i] || d->was[i]) {
            f->touches[f->count++] = (lv_indev_touch_data_t){
                .point = {scaled(d->x[i], d->xmin, d->xmax, 640),
                          scaled(d->y[i], d->ymin, d->ymax, 960)},
                .state = d->active[i] ? LV_INDEV_STATE_PRESSED
                                      : LV_INDEV_STATE_RELEASED,
                .id = i,
                .timestamp = (uint32_t)(e.input_event_sec * 1000ULL +
                                        e.input_event_usec / 1000)};
          }
          d->was[i] = d->active[i];
        }
        if (!active)
          owner = -1;
        f->sequence = ++sequence;
        return 1;
      }
      if (d->dropped)
        continue;
      if (e.type == EV_ABS) {
        if (d->mt && e.code == ABS_MT_SLOT) {
          d->slot = e.value;
          continue;
        }
        int s = d->slot;
        if (s < 0 || s >= d->slots)
          continue;
        if (d->mt && e.code == ABS_MT_TRACKING_ID)
          d->active[s] = e.value >= 0;
        else if (e.code == (d->mt ? ABS_MT_POSITION_X : ABS_X))
          d->x[s] = e.value;
        else if (e.code == (d->mt ? ABS_MT_POSITION_Y : ABS_Y))
          d->y[s] = e.value;
      } else if (!d->mt && e.type == EV_KEY && e.code == BTN_TOUCH)
        d->active[0] = !!e.value;
    }
  }
  return 0;
}
void soy_input_close(void) {
  for (int i = 0; i < 8; i++)
    if (devices[i].used) {
      close(devices[i].fd);
      devices[i].used = 0;
    }
}
int soy_input_devices(int virtual_only) {
  int n = 0;
  for (int i = 0; i < 8; i++)
    if (devices[i].used && (!virtual_only || devices[i].virtual_device))
      n++;
  return n;
}
unsigned long soy_input_events(void) { return events; }
unsigned long soy_input_drops(void) { return drops; }
