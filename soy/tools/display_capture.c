#define _GNU_SOURCE
#include <drm/drm.h>
#include <drm/drm_mode.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
/* Read the kernel's active KMS buffer, which differs from /dev/fb0 while the
 * direct Soy renderer owns the display. Does not modify display state. The
 * operator briefly pauses only that renderer to avoid a torn capture. */
int main(void) {
  int result = 1, fd = open("/dev/dri/card0", O_RDWR | O_CLOEXEC);
  if (fd < 0)
    return 1;
  uint32_t id = 0;
  struct drm_mode_card_res resources = {.crtc_id_ptr = (uintptr_t)&id,
                                        .count_crtcs = 1};
  struct drm_mode_crtc crtc = {0};
  struct drm_mode_fb_cmd fb = {0};
  void *map = MAP_FAILED;
  size_t length = 0;
  if (ioctl(fd, DRM_IOCTL_MODE_GETRESOURCES, &resources) ||
      resources.count_crtcs != 1)
    goto done;
  crtc.crtc_id = id;
  if (ioctl(fd, DRM_IOCTL_MODE_GETCRTC, &crtc) || !crtc.mode_valid)
    goto done;
  fb.fb_id = crtc.fb_id;
  if (ioctl(fd, DRM_IOCTL_MODE_GETFB, &fb) || fb.width != 640 ||
      fb.height != 960 || fb.bpp != 32 || fb.depth != 24 || fb.pitch != 2560 ||
      !fb.handle)
    goto done;
  length = (size_t)fb.pitch * fb.height;
  struct drm_mode_map_dumb dumb = {.handle = fb.handle};
  if (ioctl(fd, DRM_IOCTL_MODE_MAP_DUMB, &dumb))
    goto done;
  map = mmap(NULL, length, PROT_READ, MAP_SHARED, fd, dumb.offset);
  if (map == MAP_FAILED)
    goto done;
  printf("P6\n640 960\n255\n");
  for (int y = 0; y < 960; y++) {
    unsigned char row[640 * 3];
    for (int x = 0; x < 640; x++) {
      uint32_t value = ((const uint32_t *)map)[y * 640 + x];
      row[x * 3] = value >> 16;
      row[x * 3 + 1] = value >> 8;
      row[x * 3 + 2] = value;
    }
    if (fwrite(row, 1, sizeof row, stdout) != sizeof row)
      goto done;
  }
  result = fflush(stdout) ? 1 : 0;
done:
  if (map != MAP_FAILED)
    munmap(map, length);
  if (fb.handle) {
    struct drm_gem_close close_handle = {.handle = fb.handle};
    ioctl(fd, DRM_IOCTL_GEM_CLOSE, &close_handle);
  }
  close(fd);
  return result;
}
