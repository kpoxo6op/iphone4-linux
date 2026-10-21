#define _GNU_SOURCE
#include "display.h"
#include <errno.h>
#if defined(__arm__) && defined(__linux__)
#include <drm/drm.h>
#include <drm/drm_mode.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
#ifdef __ARM_NEON
#include <arm_neon.h>
#endif
#include <stdlib.h>

/* Fixed-panel adapter, using the toolchain's Linux DRM UAPI. Unlike the
 * general LVGL DRM driver, this doesn't wait for a synthetic page flip or
 * copy between two shadow buffers. simpledrm copies declared damage to the
 * existing boot framebuffer synchronously in DIRTYFB. No register access.
 */
static int fd = -1, active;
static uint32_t connector;
static struct drm_mode_crtc previous;
static struct drm_mode_create_dumb buffer;
static struct drm_mode_fb_cmd framebuffer;
static void *mapped = MAP_FAILED;

/*
 * Direct scanout copy. simpledrm's DIRTYFB copies damage into the boot
 * framebuffer with the kernel memcpy: 9.5 ms for a full frame on the phone.
 * The same frame copied with 128-bit NEON stores through a write-combined
 * /dev/mem mapping of that framebuffer takes 3.3 ms (22 October 2026). The
 * DRM state above is unchanged; only who copies the pixels changes.
 * LVGL renders into a cached heap buffer. SOY_SCANOUT=dirtyfb restores the
 * kernel copy.
 */
static uint8_t *scanout = MAP_FAILED, *shadow;
static int memfd = -1;

static unsigned long scanout_base(void) {
  FILE *f = fopen("/proc/iomem", "r");
  char line[256];
  unsigned long start = 0, end = 0, found = 0;
  if (!f)
    return 0;
  while (fgets(line, sizeof line, f))
    if (strstr(line, ": simpledrm") &&
        sscanf(line, " %lx-%lx", &start, &end) == 2 &&
        end - start + 1 >= 640 * 960 * 4) {
      found = start;
      break;
    }
  fclose(f);
  return found;
}

static void scanout_close(void) {
  if (scanout != MAP_FAILED)
    munmap(scanout, 640 * 960 * 4);
  scanout = MAP_FAILED;
  if (memfd >= 0)
    close(memfd);
  memfd = -1;
  free(shadow);
  shadow = NULL;
}

static uint8_t *scanout_open(void) {
  const char *mode = getenv("SOY_SCANOUT");
  unsigned long base;
  if ((mode && !strcmp(mode, "dirtyfb")) || !(base = scanout_base()))
    return NULL;
  memfd = open("/dev/mem", O_RDWR | O_SYNC | O_CLOEXEC);
  if (memfd < 0)
    return NULL;
  scanout = mmap(NULL, 640 * 960 * 4, PROT_READ | PROT_WRITE, MAP_SHARED, memfd,
                 (off_t)base);
  if (scanout == MAP_FAILED ||
      posix_memalign((void **)&shadow, 64, 640 * 960 * 4)) {
    scanout_close();
    return NULL;
  }
  return shadow;
}

static void copy_row(uint8_t *d, const uint8_t *s, size_t n) {
#ifdef __ARM_NEON
  for (; n >= 64; n -= 64, d += 64, s += 64) {
    uint8x16_t a = vld1q_u8(s), b = vld1q_u8(s + 16), c = vld1q_u8(s + 32),
               e = vld1q_u8(s + 48);
    vst1q_u8(d, a);
    vst1q_u8(d + 16, b);
    vst1q_u8(d + 32, c);
    vst1q_u8(d + 48, e);
  }
  for (; n >= 16; n -= 16, d += 16, s += 16)
    vst1q_u8(d, vld1q_u8(s));
#endif
  memcpy(d, s, n);
}

static int call(unsigned long request, void *arg) {
  int r;
  do {
    r = ioctl(fd, request, arg);
  } while (r < 0 && errno == EINTR);
  return r;
}

void soy_display_close(void) {
  if (fd < 0)
    return;
  if (active) {
    previous.set_connectors_ptr = (uintptr_t)&connector;
    previous.count_connectors = 1;
    if (call(DRM_IOCTL_MODE_SETCRTC, &previous))
      perror("Restore previous display");
  }
  if (framebuffer.fb_id)
    call(DRM_IOCTL_MODE_RMFB, &framebuffer.fb_id);
  scanout_close();
  if (mapped != MAP_FAILED)
    munmap(mapped, buffer.size);
  if (buffer.handle) {
    struct drm_mode_destroy_dumb destroy = {.handle = buffer.handle};
    call(DRM_IOCTL_MODE_DESTROY_DUMB, &destroy);
  }
  close(fd);
  fd = -1;
  active = 0;
  mapped = MAP_FAILED;
  memset(&framebuffer, 0, sizeof framebuffer);
  memset(&buffer, 0, sizeof buffer);
}

uint32_t *soy_display_open(void) {
  fd = open("/dev/dri/card0", O_RDWR | O_CLOEXEC);
  if (fd < 0)
    return NULL;
  char name[32] = {0};
  struct drm_version version = {.name = name, .name_len = sizeof name - 1};
  uint32_t crtc = 0;
  struct drm_mode_card_res resources = {.connector_id_ptr =
                                            (uintptr_t)&connector,
                                        .crtc_id_ptr = (uintptr_t)&crtc,
                                        .count_connectors = 1,
                                        .count_crtcs = 1};
  if (call(DRM_IOCTL_VERSION, &version) || strcmp(name, "simpledrm") ||
      call(DRM_IOCTL_MODE_GETRESOURCES, &resources) ||
      resources.count_connectors != 1 || resources.count_crtcs != 1)
    goto fail;
  previous.crtc_id = crtc;
  if (call(DRM_IOCTL_MODE_GETCRTC, &previous) || !previous.mode_valid ||
      previous.mode.hdisplay != 640 || previous.mode.vdisplay != 960 ||
      previous.x || previous.y)
    goto fail;
  buffer =
      (struct drm_mode_create_dumb){.width = 640, .height = 960, .bpp = 32};
  if (call(DRM_IOCTL_MODE_CREATE_DUMB, &buffer) || buffer.pitch != 2560 ||
      buffer.size < 640 * 960 * 4 || buffer.size > 4 * 1024 * 1024)
    goto fail;
  struct drm_mode_map_dumb map = {.handle = buffer.handle};
  if (call(DRM_IOCTL_MODE_MAP_DUMB, &map))
    goto fail;
  mapped = mmap(NULL, buffer.size, PROT_READ | PROT_WRITE, MAP_SHARED, fd,
                (off_t)map.offset);
  if (mapped == MAP_FAILED)
    goto fail;
  /* Preserve the old screen until the first complete LVGL frame is ready. */
  int old = open("/dev/fb0", O_RDONLY | O_CLOEXEC);
  if (old < 0)
    goto fail;
  ssize_t n = pread(old, mapped, 640 * 960 * 4, 0);
  close(old);
  if (n != 640 * 960 * 4)
    goto fail;
  framebuffer = (struct drm_mode_fb_cmd){.width = 640,
                                         .height = 960,
                                         .pitch = buffer.pitch,
                                         .bpp = 32,
                                         .depth = 24,
                                         .handle = buffer.handle};
  if (call(DRM_IOCTL_MODE_ADDFB, &framebuffer))
    goto fail;
  struct drm_mode_crtc set = previous;
  set.set_connectors_ptr = (uintptr_t)&connector;
  set.count_connectors = 1;
  set.fb_id = framebuffer.fb_id;
  if (call(DRM_IOCTL_MODE_SETCRTC, &set))
    goto fail;
  active = 1;
  uint8_t *direct = scanout_open();
  if (direct)
    memcpy(direct, mapped, 640 * 960 * 4);
  if (soy_display_present(0, 0, 640, 960))
    goto fail;
  return direct ? (uint32_t *)direct : mapped;
fail:
  soy_display_close();
  errno = ENOTSUP;
  return NULL;
}

int soy_display_present(int x1, int y1, int x2, int y2) {
  if (fd < 0 || !active || x1 < 0 || y1 < 0 || x2 > 640 || y2 > 960 ||
      x2 <= x1 || y2 <= y1) {
    errno = EINVAL;
    return -1;
  }
  if (scanout != MAP_FAILED) {
    /* 16-byte aligned spans: 4 pixels either side at most. */
    size_t from = (size_t)(x1 & ~3) * 4, to = (size_t)((x2 + 3) & ~3) * 4;
    for (int y = y1; y < y2; y++)
      copy_row(scanout + y * 2560 + from, shadow + y * 2560 + from, to - from);
    return 0;
  }
  struct drm_clip_rect clip = {.x1 = x1, .y1 = y1, .x2 = x2, .y2 = y2};
  struct drm_mode_fb_dirty_cmd dirty = {.fb_id = framebuffer.fb_id,
                                        .num_clips = 1,
                                        .clips_ptr = (uintptr_t)&clip};
  return call(DRM_IOCTL_MODE_DIRTYFB, &dirty);
}
#else
#include <stddef.h>
uint32_t *soy_display_open(void) {
  errno = ENOTSUP;
  return NULL;
}
int soy_display_present(int x1, int y1, int x2, int y2) {
  (void)x1;
  (void)y1;
  (void)x2;
  (void)y2;
  errno = ENOTSUP;
  return -1;
}
void soy_display_close(void) {}
#endif
