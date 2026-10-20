#ifndef SOY_PINCH_DRAW_H
#define SOY_PINCH_DRAW_H
#include <lvgl/lvgl.h>
void soy_pinch_draw_init(void);
void soy_pinch_draw_source(const lv_draw_buf_t *source);
int soy_snapshot_dim(lv_draw_buf_t *source, uint8_t opacity);
#endif
