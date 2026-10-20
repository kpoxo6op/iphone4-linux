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
  if (soy_display_present(0, 0, 640, 960))
    goto fail;
  return mapped;
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
