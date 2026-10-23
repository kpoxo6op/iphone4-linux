#ifndef SOY_DISPLAY_H
#define SOY_DISPLAY_H
#include <stdint.h>
/* The N90 simpledrm path has no hardware page flip/vblank. Present completes
 * the kernel's damage copy, not a synchronized panel scanout. */
uint32_t *soy_display_open(void);
int soy_display_present(int x1, int y1, int x2, int y2);
void soy_display_close(void);
/* Stop (0) or restart (1) the controller's reads of the framebuffer while
 * the screen is blanked. -1 where that is not possible. */
int soy_display_scanout(int on);
#endif
