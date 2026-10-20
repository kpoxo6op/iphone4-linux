#include "pinch_draw.h"
#ifdef SOY_PIXMAN
#include "src/draw/lv_draw_private.h"
#include "src/misc/lv_area_private.h"
#include <pixman.h>
/* LVGL's draw-unit extension, pinned with LVGL 9.6. Pixman handles flat fills,
 * our tagged immutable images and the opaque pinch snapshot. Layout, clips,
 * task ordering and unsupported drawing stay with LVGL. Drawing straight into
 * the target avoids an intermediate full-body image. */
#define SOY_PINCH_UNIT 64
static const lv_draw_buf_t *preview;
static int32_t evaluate(lv_draw_unit_t *unit, lv_draw_task_t *task) {
  (void)unit;
  if (task->target_layer->color_format != LV_COLOR_FORMAT_XRGB8888)
    return 0;
  if (task->type == LV_DRAW_TASK_TYPE_FILL) {
    lv_draw_fill_dsc_t *d = task->draw_dsc;
    if (d->radius || d->grad.dir != LV_GRAD_DIR_NONE)
      return 0;
    task->preference_score = 20;
    task->preferred_draw_unit_id = SOY_PINCH_UNIT;
    return 1;
  }
  if (task->type != LV_DRAW_TASK_TYPE_IMAGE)
    return 0;
  lv_draw_image_dsc_t *d = task->draw_dsc;
  if (d->tile || d->image_area.x1 != task->area.x1 ||
      d->image_area.y1 != task->area.y1 || d->image_area.x2 != task->area.x2 ||
      d->image_area.y2 != task->area.y2)
    return 0;
  if (d->src != preview && (!(d->header.flags & LV_IMAGE_FLAGS_USER1) ||
                            d->scale_x != 256 || d->scale_y != 256))
    return 0;
  if ((d->header.cf != LV_COLOR_FORMAT_XRGB8888 &&
       !(d->header.cf == LV_COLOR_FORMAT_ARGB8888 &&
         (d->header.flags & LV_IMAGE_FLAGS_PREMULTIPLIED))) ||
      task->target_layer->color_format != LV_COLOR_FORMAT_XRGB8888 ||
      d->rotation || d->skew_x || d->skew_y || d->recolor_opa ||
      d->opa != LV_OPA_COVER || d->clip_radius || d->bitmap_mask_src ||
      d->scale_x <= 0 || d->scale_y <= 0 ||
      d->blend_mode != LV_BLEND_MODE_NORMAL)
    return 0;
  task->preference_score = 20;
  task->preferred_draw_unit_id = SOY_PINCH_UNIT;
  return 1;
}
static int32_t dispatch(lv_draw_unit_t *unit, lv_layer_t *layer) {
  (void)unit;
  lv_draw_task_t *task =
      lv_draw_get_available_task(layer, NULL, SOY_PINCH_UNIT);
  if (!task)
    return LV_DRAW_UNIT_IDLE;
  if (!lv_draw_layer_alloc_buf(layer)) {
    task->state = LV_DRAW_TASK_STATE_FAILED;
    return LV_DRAW_UNIT_IDLE;
  }
  task->state = LV_DRAW_TASK_STATE_IN_PROGRESS;
  lv_area_t clip;
  if (lv_area_intersect(&clip, &task->_real_area, &task->clip_area) &&
      lv_area_intersect(&clip, &clip, &layer->buf_area)) {
    lv_draw_buf_t *dest = layer->draw_buf;
    pixman_image_t *dst = pixman_image_create_bits(
        PIXMAN_x8r8g8b8, dest->header.w, dest->header.h, (uint32_t *)dest->data,
        dest->header.stride);
    pixman_image_t *src = NULL;
    pixman_op_t op = PIXMAN_OP_SRC;
    int sx = 0, sy = 0;
    if (task->type == LV_DRAW_TASK_TYPE_FILL) {
      lv_draw_fill_dsc_t *d = task->draw_dsc;
      pixman_color_t c = {
          .red = (uint16_t)(d->color.red * 257u * d->opa / 255u),
          .green = (uint16_t)(d->color.green * 257u * d->opa / 255u),
          .blue = (uint16_t)(d->color.blue * 257u * d->opa / 255u),
          .alpha = d->opa * 257u};
      src = pixman_image_create_solid_fill(&c);
      if (d->opa != LV_OPA_COVER)
        op = PIXMAN_OP_OVER;
    } else {
      lv_draw_image_dsc_t *d = task->draw_dsc;
      const lv_image_dsc_t *image = d->src;
      int opaque = d->header.cf == LV_COLOR_FORMAT_XRGB8888;
      src = pixman_image_create_bits(
          opaque ? PIXMAN_x8r8g8b8 : PIXMAN_a8r8g8b8, image->header.w,
          image->header.h, (uint32_t *)image->data, image->header.stride);
      op = opaque ? PIXMAN_OP_SRC : PIXMAN_OP_OVER;
      sx = clip.x1 - task->area.x1;
      sy = clip.y1 - task->area.y1;
      if (src && (d->scale_x != 256 || d->scale_y != 256)) {
        double ix = 256.0 / d->scale_x, iy = 256.0 / d->scale_y;
        pixman_transform_t transform;
        pixman_transform_init_scale(&transform, pixman_double_to_fixed(ix),
                                    pixman_double_to_fixed(iy));
        transform.matrix[0][2] = pixman_double_to_fixed(d->pivot.x * (1 - ix));
        transform.matrix[1][2] = pixman_double_to_fixed(d->pivot.y * (1 - iy));
        pixman_image_set_transform(src, &transform);
        pixman_image_set_filter(src, PIXMAN_FILTER_NEAREST, NULL, 0);
        pixman_image_set_repeat(src, PIXMAN_REPEAT_PAD);
      }
    }
    if (!src || !dst) {
      if (src)
        pixman_image_unref(src);
      if (dst)
        pixman_image_unref(dst);
      task->state = LV_DRAW_TASK_STATE_FAILED;
      return LV_DRAW_UNIT_IDLE;
    }
    pixman_image_composite32(
        op, src, NULL, dst, sx, sy, 0, 0, clip.x1 - layer->buf_area.x1,
        clip.y1 - layer->buf_area.y1, lv_area_get_width(&clip),
        lv_area_get_height(&clip));
    pixman_image_unref(src);
    pixman_image_unref(dst);
  }
  task->state = LV_DRAW_TASK_STATE_FINISHED;
  lv_draw_dispatch_request();
  return 1;
}
void soy_pinch_draw_init(void) {
  lv_draw_unit_t *unit = lv_draw_create_unit(sizeof(*unit));
  unit->name = "Soy Pixman";
  unit->evaluate_cb = evaluate;
  unit->dispatch_cb = dispatch;
}
void soy_pinch_draw_source(const lv_draw_buf_t *source) { preview = source; }
int soy_snapshot_dim(lv_draw_buf_t *source, uint8_t opacity) {
  pixman_color_t black = {.alpha = opacity * 257u};
  pixman_image_t *src = pixman_image_create_solid_fill(&black);
  pixman_image_t *dst = pixman_image_create_bits(
      PIXMAN_x8r8g8b8, source->header.w, source->header.h,
      (uint32_t *)source->data, source->header.stride);
  if (src && dst)
    pixman_image_composite32(PIXMAN_OP_OVER, src, NULL, dst, 0, 0, 0, 0, 0, 0,
                             source->header.w, source->header.h);
  int result = src && dst ? 0 : -1;
  if (src)
    pixman_image_unref(src);
  if (dst)
    pixman_image_unref(dst);
  return result;
}
#else
void soy_pinch_draw_init(void) {}
void soy_pinch_draw_source(const lv_draw_buf_t *source) { (void)source; }
int soy_snapshot_dim(lv_draw_buf_t *source, uint8_t opacity) {
  (void)source;
  (void)opacity;
  return -1;
}
#endif
