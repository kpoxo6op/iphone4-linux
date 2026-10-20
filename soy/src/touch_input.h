#ifndef SOY_TOUCH_INPUT_H
#define SOY_TOUCH_INPUT_H
#include <lvgl/lvgl.h>
#include <poll.h>
#define SOY_CONTACTS 16
typedef struct {
  lv_indev_touch_data_t touches[SOY_CONTACTS];
  int count, active, cancel, virtual_device;
  unsigned long sequence;
} SoyContacts;
/* A frame is one kernel SYN_REPORT. No queued contact transitions are
 * collapsed. */
void soy_input_scan(void);
int soy_input_pollfds(struct pollfd *fds, int capacity);
int soy_input_next(SoyContacts *frame);
void soy_input_close(void);
int soy_input_devices(int virtual_only);
unsigned long soy_input_events(void);
unsigned long soy_input_drops(void);
#endif
