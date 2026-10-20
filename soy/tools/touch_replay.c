#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <linux/uinput.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

/* A bounded stdin-driven Type B touchscreen for unattended integration tests.
 * Coordinates are deliberately 0..4095, not display pixels. No physical input
 * hardware is replaced, grabbed, or represented as tested by this utility. */
static int fd = -1;
static void event(int type, int code, int value) {
  struct input_event e = {.type = type, .code = code, .value = value};
  if (write(fd, &e, sizeof e) != sizeof e) {
    perror("uinput write");
    exit(2);
  }
}
static void destroy(void) {
  if (fd >= 0) {
    ioctl(fd, UI_DEV_DESTROY);
    close(fd);
    fd = -1;
  }
}
static void create(void) {
  fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK | O_CLOEXEC);
  if (fd < 0) {
    perror("uinput");
    exit(2);
  }
  ioctl(fd, UI_SET_EVBIT, EV_KEY);
  ioctl(fd, UI_SET_KEYBIT, BTN_TOUCH);
  ioctl(fd, UI_SET_EVBIT, EV_ABS);
  ioctl(fd, UI_SET_PROPBIT, INPUT_PROP_DIRECT);
  int axes[] = {ABS_MT_SLOT, ABS_MT_TRACKING_ID, ABS_MT_POSITION_X,
                ABS_MT_POSITION_Y};
  for (int i = 0; i < 4; i++)
    if (ioctl(fd, UI_SET_ABSBIT, axes[i])) {
      perror("UI_SET_ABSBIT");
      exit(2);
    }
  struct uinput_user_dev d = {0};
  snprintf(d.name, sizeof d.name, "Soy replay (virtual)");
  d.id.bustype = BUS_VIRTUAL;
  d.id.vendor = 0x1209;
  d.id.product = 0x534f;
  d.id.version = 1;
  d.absmax[ABS_MT_SLOT] = 15;
  d.absmax[ABS_MT_TRACKING_ID] = 65535;
  d.absmax[ABS_MT_POSITION_X] = d.absmax[ABS_MT_POSITION_Y] = 4095;
  if (write(fd, &d, sizeof d) != sizeof d || ioctl(fd, UI_DEV_CREATE)) {
    perror("UI_DEV_CREATE");
    exit(2);
  }
}
int main(void) {
  /* Closing stdin, a terminated SSH session, or the test deadline removes it.
   */
  alarm(600);
  atexit(destroy);
  create();
  puts("ready");
  fflush(stdout);
  char line[256];
  while (fgets(line, sizeof line, stdin)) {
    char op[32];
    int slot, id, x, y;
    if (sscanf(line, "%31s", op) != 1)
      continue;
    if (!strcmp(op, "quit"))
      break;
    if (!strcmp(op, "disconnect")) {
      destroy();
      puts("disconnected");
      fflush(stdout);
      continue;
    }
    if (!strcmp(op, "connect")) {
      if (fd < 0)
        create();
      puts("connected");
      fflush(stdout);
      continue;
    }
    if (!strcmp(op, "wait") && sscanf(line, "%*s %d", &x) == 1) {
      if (x < 0 || x > 5000)
        return 2;
      struct timespec t = {x / 1000, (x % 1000) * 1000000L};
      while (nanosleep(&t, &t) && errno == EINTR) {
      }
      continue;
    }
    if (!strcmp(op, "sample")) {
      FILE *f = fopen("/run/soy/status.json", "r");
      char state[4096];
      if (!f || !fgets(state, sizeof state, f))
        return 2;
      fclose(f);
      printf("state:%s", state);
      fflush(stdout);
      continue;
    }
    if (!strcmp(op, "ack")) {
      puts("ack");
      fflush(stdout);
      continue;
    }
    if (!strcmp(op, "mark")) {
      char name[32];
      struct timespec t;
      if (sscanf(line, "%*s %31s", name) != 1 ||
          clock_gettime(CLOCK_MONOTONIC, &t))
        return 2;
      printf("mark:%s %.9f\n", name, t.tv_sec + t.tv_nsec / 1e9);
      fflush(stdout);
      continue;
    }
    if (fd < 0)
      return 2;
    if (!strcmp(op, "down") &&
        sscanf(line, "%*s %d %d %d %d", &slot, &id, &x, &y) == 4) {
      if (slot < 0 || slot > 15 || id < 0 || id > 65535 || x < 0 || x > 4095 ||
          y < 0 || y > 4095)
        return 2;
      event(EV_ABS, ABS_MT_SLOT, slot);
      event(EV_ABS, ABS_MT_TRACKING_ID, id);
      event(EV_ABS, ABS_MT_POSITION_X, x);
      event(EV_ABS, ABS_MT_POSITION_Y, y);
      event(EV_KEY, BTN_TOUCH, 1);
    } else if (!strcmp(op, "move") &&
               sscanf(line, "%*s %d %d %d", &slot, &x, &y) == 3) {
      if (slot < 0 || slot > 15 || x < 0 || x > 4095 || y < 0 || y > 4095)
        return 2;
      event(EV_ABS, ABS_MT_SLOT, slot);
      event(EV_ABS, ABS_MT_POSITION_X, x);
      event(EV_ABS, ABS_MT_POSITION_Y, y);
    } else if (!strcmp(op, "up") && sscanf(line, "%*s %d", &slot) == 1) {
      if (slot < 0 || slot > 15)
        return 2;
      event(EV_ABS, ABS_MT_SLOT, slot);
      event(EV_ABS, ABS_MT_TRACKING_ID, -1);
    } else if (!strcmp(op, "frame"))
      event(EV_SYN, SYN_REPORT, 0);
    else if (!strcmp(op, "drop"))
      event(EV_SYN, SYN_DROPPED, 0);
    else if (!strcmp(op, "flood")) {
      for (int i = 0; i < 20000; i++) {
        event(EV_ABS, ABS_MT_POSITION_X, 1000 + i % 2000);
        event(EV_SYN, SYN_REPORT, 0);
      }
    } else {
      fprintf(stderr, "Bad replay command\n");
      return 2;
    }
  }
  return 0;
}
