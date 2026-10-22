#define _GNU_SOURCE
#include "display.h"
#include "pinch_draw.h"
#include "scene_data.h"
#include "touch_input.h"
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <linux/fb.h>
#include <linux/input.h>
#include <linux/kd.h>
#include <lvgl/lvgl.h>
#include <math.h>
#include <poll.h>
#include <sched.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/ioctl.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <time.h>
#include <unistd.h>

/* LVGL supplies rendering, hit testing, scroll physics, snapping, recognizers,
 * timers and animation. This file supplies the text scene and phone UI policy.
 */
#define MAX_BLOCKS 2048
#define MAX_BINDINGS 128
static lv_font_t faces[14];
static Font extra_fonts[3];
static const int body_faces[] = {4, 1, 5, 2, 6};
static const int body_sizes[] = {32, 36, 42, 48, 54};
typedef struct {
  lv_obj_t *obj;
  char *raw;
  int font, graph;
} Live;
typedef struct {
  lv_obj_t *page, *body, **blocks;
  lv_draw_buf_t **cached;
  int nblocks, zoom, live_count, height;
  Live live[MAX_BINDINGS];
} View;
static View views[NS];
/* Inactive font layouts have independent object/buffer ownership. */
static View prepared[NS][5];
static lv_obj_t *page_images[NS];
static lv_obj_t *page_headers[NS];
static int page_dirty[NS];
static size_t cache_bytes;
#define CACHE_LIMIT (160u * 1024 * 1024)
static lv_obj_t *pinch_preview, *pinch_layer;
static lv_draw_buf_t *pinch_image;
static int pinch_level;
static float preview_scale = 1;
static lv_obj_t *pager, *dots[9], *nav, *sheet, *sheet_card;
static lv_obj_t *sheet_backdrop;
static lv_obj_t *sheet_picture;
static lv_obj_t *sheet_shield;
static lv_display_t *display;
static lv_indev_t *pointer;
static lv_obj_t *blank_screen;
static unsigned idle_seconds = 60;
/* -1: no backlight device, 0: off, 1: on. */
static int backlight_state = -1;
static int keyfd = -1;
static int wake_contact;
static uint32_t fallback_pixels[W * H];
static uint32_t *pixels = fallback_pixels;
static int direct_display;
#define PIXEL_BYTES (W * H * sizeof(uint32_t))
static int fb = -1, ctl = -1, headless, sheet_kind, sheet_height,
           sheet_initializing;
static int ttyfd = -1, tty_mode = -1;
static int close_pending, rebuild_pending, zoom_pending = -1,
                                           zoom_anchor = H / 2;
static int contacts_active, multi_latched, multi_canceled, primary = -1,
                                                           pointer_pressed;
static lv_point_t pointer_point;
static int pinch_base, pinch_index, reload_requested, press_stopped_motion;
static unsigned long input_sequence, frames, pinch_events, tap_events;
static volatile sig_atomic_t stopping, reloading;
static double frame_start, render_sum, render_max, render_samples[256],
    frame_times[256];
static double input_time, latency_max, transfer_sum, transfer_max;
static double frame_cpu_start, input_work_ms, stats_end, stats_ms, status_end,
    status_ms;
#define TRACE_FRAMES 4096
typedef struct {
  double start, end, transfer;
  unsigned long input;
  int scene, scroll, page, panel, contacts;
  float scale;
  double cpu_end, render_cpu, transfer_cpu, input_work;
  double stats_end, stats_ms, status_end, status_ms;
  int x1, y1, x2, y2;
  int panel_kind, font_px;
  long voluntary, involuntary;
} Frame;
static Frame trace[TRACE_FRAMES];
static lv_area_t damage;
static char rundir[512] = "/run/soy";
static void build_pages(void);
static void end_preview(int commit);
static void open_sheet(int kind, int from_edge);
static void close_sheet(void);
static void go(int index, int animate);
static void resize_text(int index, int level, int anchor);

static uint32_t ticks(void) { return (uint32_t)(now() * 1000); }
static double thread_cpu_ms(void) {
  struct timespec t;
  clock_gettime(CLOCK_THREAD_CPUTIME_ID, &t);
  return t.tv_sec * 1000.0 + t.tv_nsec / 1000000.0;
}
static void signal_handler(int s) {
  if (s == SIGHUP)
    reloading = 1;
  else
    stopping = 1;
}
/* The journal: what the phone showed and when, so the AI that draws the
 * scenes can learn what was read (soy/tools/scene.py journal pulls it).
 * JSON lines in the run directory, kept to about 1 MiB with one rotation. */
static FILE *journal;
static char noted_scene[48];
static double battery_noted = -1;
static void note(const char *fmt, ...) {
  if (!journal)
    return;
  struct timespec ts;
  clock_gettime(CLOCK_REALTIME, &ts);
  fprintf(journal, "{\"t\":%lld.%03ld,", (long long)ts.tv_sec,
          ts.tv_nsec / 1000000);
  va_list ap;
  va_start(ap, fmt);
  vfprintf(journal, fmt, ap);
  va_end(ap);
  fputs("}\n", journal);
  fflush(journal);
  if (ftell(journal) > 1 << 20) {
    char p[600], old[600];
    path(p, sizeof p, rundir, "journal.jsonl");
    path(old, sizeof old, rundir, "journal.1.jsonl");
    fclose(journal);
    rename(p, old);
    journal = fopen(p, "ae");
  }
}
/* A settled scene change, with how far the scene being left was read. */
static void note_scene(void) {
  if (current >= count || !strcmp(noted_scene, scenes[current].id))
    return;
  int left = -1;
  for (int i = 0; i < count; i++)
    if (!strcmp(scenes[i].id, noted_scene))
      left = i;
  if (left >= 0)
    note("\"e\":\"scene\",\"scene\":\"%s\",\"left\":\"%s\",\"scroll\":%d,"
         "\"height\":%d",
         scenes[current].id, scenes[left].id, scenes[left].scroll,
         scenes[left].height);
  else
    note("\"e\":\"scene\",\"scene\":\"%s\"", scenes[current].id);
  snprintf(noted_scene, sizeof noted_scene, "%s", scenes[current].id);
}
static lv_color_t color(uint32_t c) { return lv_color_hex(c); }
static void flat(lv_obj_t *o) {
  lv_obj_remove_style_all(o);
  lv_obj_set_style_bg_color(o, color(BG), 0);
  lv_obj_set_style_bg_opa(o, LV_OPA_COVER, 0);
  lv_obj_set_style_text_color(o, color(INK), 0);
  lv_obj_set_style_text_font(o, &faces[1], 0);
  lv_obj_set_style_anim_duration(o, 220, 0);
  lv_obj_set_scrollbar_mode(o, LV_SCROLLBAR_MODE_OFF);
}
static bool glyph_desc(const lv_font_t *face, lv_font_glyph_dsc_t *g,
                       uint32_t c, uint32_t next) {
  (void)next;
  Font *f = face->user_data;
  if (c == '\n' || c == '\r')
    return true;
  const unsigned char *p = glyph(f, c);
  if (!p)
    return false;
  g->adv_w = f->w;
  g->box_w = f->w;
  g->box_h = f->h;
  g->format = LV_FONT_GLYPH_FORMAT_A8;
  g->gid.src = p;
  g->stride = f->w;
  return true;
}
static const void *glyph_bitmap(lv_font_glyph_dsc_t *g, lv_draw_buf_t *b) {
  if (g->req_raw_bitmap)
    return g->gid.src;
  const unsigned char *src = g->gid.src;
  for (int y = 0; y < g->box_h; y++) {
    unsigned char *row = b->data + y * b->header.stride;
    memcpy(row, src + y * g->stride, g->box_w);
    if (g->resolved_font->dsc)
      for (int x = g->box_w - 1; x > 0; x--)
        if (row[x - 1] > row[x])
          row[x] = row[x - 1];
  }
  return b;
}
static int init_fonts(void) {
  const int sizes[] = {24, 36, 48, 96, 32, 42, 54};
  for (int i = 0; i < 7; i++) {
    Font *f = i < 4 ? &fonts[i] : &extra_fonts[i - 4];
    if (load_font(f, sizes[i]))
      return -1;
    faces[i] = (lv_font_t){.get_glyph_dsc = glyph_desc,
                           .get_glyph_bitmap = glyph_bitmap,
                           .line_height = f->h,
                           .base_line = 0,
                           .user_data = f,
                           .kerning = LV_FONT_KERNING_NONE,
                           .underline_position = -2,
                           .underline_thickness = 2};
  }
  for (int i = 0; i < 7; i++) {
    faces[i + 7] = faces[i];
    faces[i + 7].dsc = (void *)1;
  }
  return 0;
}
static void free_label_image(lv_event_t *e) {
  lv_draw_buf_t *buf = lv_event_get_user_data(e);
  cache_bytes -= buf->data_size;
  lv_draw_buf_destroy(buf);
}
static lv_obj_t *label(lv_obj_t *parent, const char *text, int font,
                       uint32_t ink, int x, int y, int w) {
  lv_obj_t *o = lv_label_create(parent);
  lv_obj_set_style_text_font(o, &faces[font], 0);
  lv_obj_set_style_text_color(o, color(ink), 0);
  lv_obj_set_style_text_line_space(o, 3, 0);
  lv_label_set_text(o, text);
  lv_obj_set_pos(o, x, y);
  lv_obj_set_width(o, w);
  lv_obj_set_clickable(o, false);
  lv_obj_update_layout(o);
  size_t bytes = (size_t)w * lv_obj_get_height(o) * 4;
  if (bytes < CACHE_LIMIT && cache_bytes + bytes < CACHE_LIMIT) {
    /* Text is immutable for this object's lifetime. Transparent cached glyphs
     * retain the real button's pressed background and native hit testing. */
    lv_draw_buf_t *buf = lv_snapshot_take(o, LV_COLOR_FORMAT_ARGB8888);
    if (buf) {
      /* LVGL's ARMv7 NEON path accepts premultiplied glyph snapshots. Its
       * straight-alpha ARGB path deliberately falls back to scalar blending. */
      lv_draw_buf_premultiply(buf);
      lv_draw_buf_set_flag(buf, LV_IMAGE_FLAGS_USER1);
      lv_obj_t *image = lv_image_create(parent);
      lv_image_set_src(image, buf);
      lv_obj_set_pos(image, x, y);
      lv_obj_set_clickable(image, false);
      lv_obj_add_event_cb(image, free_label_image, LV_EVENT_DELETE, buf);
      cache_bytes += buf->data_size;
      lv_obj_delete(o);
      o = image;
    }
  }
  return o;
}
static void add_span(lv_obj_t *o, const char *s, int font, uint32_t ink,
                     int bold) {
  lv_span_t *span = lv_spangroup_add_span(o);
  lv_span_set_text(span, s);
  lv_style_t *style = lv_span_get_style(span);
  lv_style_set_text_font(style, &faces[font + (bold ? 7 : 0)]);
  lv_style_set_text_color(style, color(ink));
}
static void markdown(lv_obj_t *o, const char *s, int font, uint32_t ink,
                     uint32_t accent, int code, int bold) {
  /* Preserve the small, safe Markdown dialect. URLs are text, never commands.
   */
  char *part = malloc(strlen(s) + 1);
  if (!part)
    return;
  size_t n = 0;
  int em = 0, link = 0, mono = code;
  while (*s) {
    int step = 0, kind = 0;
    if (!code && s[0] == '*' && s[1] == '*') {
      step = 2;
      kind = 1;
    } else if (!code && *s == '*') {
      step = 1;
      kind = 2;
    } else if (!code && *s == '`') {
      step = 1;
      kind = 3;
    } else if (!code && *s == '[') {
      step = 1;
      kind = 4;
    } else if (!code && *s == ']' && s[1] == '(') {
      const char *end = strchr(s + 2, ')');
      if (end) {
        step = end - s + 1;
        kind = 5;
      }
    }
    if (step) {
      if (n) {
        part[n] = 0;
        add_span(o, part, font, link || mono ? accent : em ? MUTED : ink, bold);
        n = 0;
      }
      if (kind == 1)
        bold = !bold;
      else if (kind == 2)
        em = !em;
      else if (kind == 3)
        mono = !mono;
      else if (kind == 4)
        link = 1;
      else
        link = 0;
      s += step;
    } else {
      if (*s == '\\' && s[1])
        s++;
      part[n++] = *s++;
    }
  }
  if (n) {
    part[n] = 0;
    add_span(o, part, font, link || mono ? accent : em ? MUTED : ink, bold);
  }
  free(part);
  lv_spangroup_refresh(o);
}
static int graph_block(View *v, int y, int battery_graph, uint32_t accent) {
  int n = battery_graph ? bn : nn;
  double *samples = battery_graph ? battery_history : network_history;
  if (!n) {
    label(v->body, "No history yet", 1, MUTED, 34, y + 20, 572);
    return y + 100;
  }
  double max = battery_graph ? 100 : 1;
  for (int i = 0; i < n; i++)
    if (samples[i] > max)
      max = samples[i];
  char scale[64];
  if (battery_graph)
    snprintf(scale, sizeof scale, "100%%");
  else
    pretty_bytes(max, scale, sizeof scale, "/s total");
  label(v->body, scale, 0, MUTED, 34, y, 572);
  lv_obj_t *chart = lv_chart_create(v->body);
  flat(chart);
  lv_obj_set_pos(chart, 34, y + 48);
  lv_obj_set_size(chart, 572, 120);
  lv_obj_set_clickable(chart, false);
  lv_obj_set_scrollable(chart, false);
  lv_chart_set_type(chart, LV_CHART_TYPE_LINE);
  lv_chart_set_point_count(chart, 60);
  lv_chart_set_axis_range(chart, LV_CHART_AXIS_PRIMARY_Y, 0, 1000);
  lv_chart_set_div_line_count(chart, 2, 0);
  lv_obj_set_style_line_color(chart, color(LINE), 0);
  lv_obj_set_style_line_width(chart, 2, LV_PART_ITEMS);
  lv_obj_set_style_size(chart, 0, 0, LV_PART_INDICATOR);
  lv_chart_series_t *series =
      lv_chart_add_series(chart, color(accent), LV_CHART_AXIS_PRIMARY_Y);
  for (int i = 0; i < 60; i++)
    lv_chart_set_next_value(chart, series,
                            i < 60 - n
                                ? LV_CHART_POINT_NONE
                                : (int)(samples[i - (60 - n)] / max * 1000));
  char age[40];
  snprintf(age, sizeof age, "−%d %s", n > 0 ? n - 1 : 0,
           battery_graph ? "min" : "s");
  label(v->body, age, 0, MUTED, 34, y + 180, 280);
  label(v->body, "now", 0, MUTED, 560, y + 180, 72);
  return y + 234;
}
static void free_blocks(View *v) {
  for (int j = 0; j < v->nblocks; j++)
    if (v->cached && v->cached[j]) {
      cache_bytes -= v->cached[j]->data_size;
      lv_draw_buf_destroy(v->cached[j]);
    }
  free(v->cached);
  v->cached = NULL;
  free(v->blocks);
  v->blocks = NULL;
  v->nblocks = 0;
  for (int j = 0; j < v->live_count; j++)
    free(v->live[j].raw);
  v->live_count = 0;
}
static void invalidate_page(int index) {
  if (page_images[index] && !page_dirty[index]) {
    lv_obj_set_hidden(page_images[index], true);
    lv_obj_set_style_bg_opa(views[index].page, LV_OPA_COVER, 0);
    lv_obj_set_style_opa(views[index].body, LV_OPA_COVER, 0);
    lv_obj_set_style_opa(page_headers[index], LV_OPA_COVER, 0);
  }
  page_dirty[index] = 1;
}
/* One bounded viewport snapshot at rest. A pager drag then moves immutable
 * images while LVGL still owns input, snapping, clipping and the live tree. */
static void prepare_page(void) {
  for (int j = 0; j < count; j++) {
    int i = (current + j) % count;
    if (!page_dirty[i])
      continue;
    if (page_images[i]) {
      lv_obj_delete(page_images[i]);
      page_images[i] = NULL;
    }
    if (cache_bytes + (size_t)W * 884 * 4 >= CACHE_LIMIT)
      return;
    lv_draw_buf_t *buf =
        lv_snapshot_take(views[i].page, LV_COLOR_FORMAT_XRGB8888);
    if (!buf)
      return;
    lv_draw_buf_set_flag(buf, LV_IMAGE_FLAGS_USER1);
    lv_obj_t *image = lv_image_create(views[i].page);
    lv_image_set_src(image, buf);
    lv_obj_set_clickable(image, false);
    lv_obj_set_hidden(image, true);
    lv_obj_add_event_cb(image, free_label_image, LV_EVENT_DELETE, buf);
    cache_bytes += buf->data_size;
    page_images[i] = image;
    page_dirty[i] = 0;
    return;
  }
}
static void build_body(int index) {
  invalidate_page(index);
  View *v = &views[index];
  Scene *s = &scenes[index];
  lv_obj_clean(v->body);
  free_blocks(v);
  v->blocks = calloc(MAX_BLOCKS, sizeof(lv_obj_t *));
  v->cached = calloc(MAX_BLOCKS, sizeof(lv_draw_buf_t *));
  if (!v->blocks || !v->cached) {
    stopping = 1;
    return;
  }
  const char *cursor = s->body;
  int y = 0, code = 0, first = 1;
  while (*cursor && v->nblocks < MAX_BLOCKS) {
    const char *end = strchr(cursor, '\n');
    size_t len = end ? (size_t)(end - cursor) : strlen(cursor);
    char *raw = strndup(cursor, len), *expanded = malloc(len + 2048);
    if (!raw || !expanded) {
      free(raw);
      free(expanded);
      break;
    }
    if (!strncmp(raw, "```", 3)) {
      code = !code;
      y += 12;
    } else if (!*raw)
      y += 20;
    else if (!strcmp(raw, "{{graph.battery}}") ||
             !strcmp(raw, "{{graph.network}}"))
      y = graph_block(v, y, !strcmp(raw, "{{graph.battery}}"), s->accent);
    else {
      expand(raw, expanded, len + 2048);
      char *txt = expanded;
      int font = body_faces[v->zoom], indent = 0, strong = 0;
      uint32_t ink = INK;
      if (!code && *txt == '#') {
        int level = 0;
        while (*txt == '#') {
          level++;
          txt++;
        }
        if (*txt == ' ')
          txt++;
        font = level == 1 ? (s->hero && first ? 3 : 2) : body_faces[v->zoom];
        strong = level > 1; /* Subheadings stay body size, set apart by weight. */
        ink = s->hero && level == 1 ? s->accent : INK;
        y += first ? 0 : 12;
        first = 0;
      } else if (!code && *txt == '>' && (txt[1] == ' ' || !txt[1])) {
        txt++;
        if (*txt == ' ')
          txt++;
        indent = 22;
        ink = MUTED;
        lv_obj_t *rule = lv_obj_create(v->body);
        flat(rule);
        lv_obj_set_pos(rule, 34, y + 8);
        lv_obj_set_size(rule, 3, faces[font].line_height - 16);
        lv_obj_set_style_bg_color(rule, color(s->accent), 0);
        lv_obj_set_clickable(rule, false);
      } else if (!code && (*txt == '-' || *txt == '*') && txt[1] == ' ') {
        label(v->body, "•", font, s->accent, 34, y, 24);
        txt += 2;
        indent = 34;
      }
      lv_obj_t *o = lv_spangroup_create(v->body);
      lv_obj_set_pos(o, 34 + indent, y);
      lv_obj_set_width(o, 572 - indent);
      lv_obj_set_style_text_font(o, &faces[font], 0);
      lv_obj_set_style_text_line_space(o, 3, 0);
      lv_obj_set_height(o, LV_SIZE_CONTENT);
      lv_obj_set_clickable(o, false);
      lv_obj_set_scrollable(o, false);
      if (code) {
        lv_obj_set_style_bg_color(o, color(0x101a14), 0);
        lv_obj_set_style_bg_opa(o, LV_OPA_COVER, 0);
        ink = s->accent;
      }
      markdown(o, txt, font, ink, s->accent, code, strong);
      lv_obj_update_layout(o);
      int height = lv_obj_get_height(o);
      /* LVGL snapshots cache immutable paragraphs. Software text layout and
       * glyph blending must not run again on every scrolling frame on the A4.
       * The budget bounds memory for large AI-generated documents. */
      size_t bytes = (size_t)lv_obj_get_width(o) * height * 4;
      if (!strstr(raw, "{{") && bytes < CACHE_LIMIT &&
          cache_bytes + bytes < CACHE_LIMIT) {
        lv_obj_set_style_bg_color(o, color(code ? 0x101a14 : BG), 0);
        lv_obj_set_style_bg_opa(o, LV_OPA_COVER, 0);
        lv_draw_buf_t *buf = lv_snapshot_take(o, LV_COLOR_FORMAT_XRGB8888);
        if (buf) {
          lv_draw_buf_set_flag(buf, LV_IMAGE_FLAGS_USER1);
          lv_obj_t *image = lv_image_create(v->body);
          lv_image_set_src(image, buf);
          lv_obj_set_pos(image, 34 + indent, y);
          lv_obj_set_clickable(image, false);
          lv_obj_delete(o);
          o = image;
          v->cached[v->nblocks] = buf;
          cache_bytes += buf->data_size;
        }
      }
      v->blocks[v->nblocks++] = o;
      y += height;
      if (strstr(raw, "{{") && v->live_count < MAX_BINDINGS)
        v->live[v->live_count++] =
            (Live){.obj = o, .raw = strdup(raw), .font = font};
    }
    free(raw);
    free(expanded);
    cursor = end ? end + 1 : cursor + len;
  }
  /* A real child sets the scroll extent; its final 24 px keep the last line
   * reachable. */
  lv_obj_t *end = lv_obj_create(v->body);
  lv_obj_remove_style_all(end);
  lv_obj_set_pos(end, 0, y);
  lv_obj_set_size(end, 1, 24);
  lv_obj_set_clickable(end, false);
  v->height = scenes[index].height = y + 24;
  lv_obj_update_layout(v->body);
}
static void update_dots(void) {
  int visible = count < 9 ? count : 9,
      first = clamp(current - visible / 2, 0, count - visible);
  for (int j = 0; j < visible; j++) {
    int active = first + j == current;
    lv_obj_set_size(dots[j], active ? 14 : 6, 6);
    lv_obj_set_pos(dots[j],
                   W / 2 - (visible - 1) * 32 / 2 + j * 32 - (active ? 7 : 3),
                   32);
    lv_obj_set_style_bg_color(dots[j], color(active ? INK : MUTED), 0);
  }
}
/* LVGL's ease-out, rounded to the nearest pixel and landing once within a
 * pixel and a half, so the last pixels do not wait out the curve's flat tail
 * (a frame that changes nothing is not drawn, and the next one comes late). */
static int32_t soy_ease_out(const lv_anim_t *a) {
  int32_t t = lv_map(a->act_time, 0, a->duration, 0, LV_BEZIER_VAL_MAX);
  int32_t step = lv_cubic_bezier(t, LV_BEZIER_VAL_FLOAT(0), LV_BEZIER_VAL_FLOAT(0),
                                 LV_BEZIER_VAL_FLOAT(0.58), LV_BEZIER_VAL_FLOAT(1));
  int64_t span = (int64_t)a->end_value - a->start_value, moved = span * step;
  if (llabs(span * LV_BEZIER_VAL_MAX - moved) < 3 * LV_BEZIER_VAL_MAX / 2)
    return a->end_value;
  return a->start_value +
         (int32_t)((moved + (moved < 0 ? -1 : 1) * LV_BEZIER_VAL_MAX / 2) /
                   LV_BEZIER_VAL_MAX);
}
/* Snaps, settles and bounces: about 180 ms for a full page and shorter for a
 * short distance, so every frame of the slide moves at least a pixel. LVGL's
 * 200 ms minimum stepped a 3 px snap once every 40 ms. */
static void pace_scroll(lv_event_t *e) {
  lv_anim_t *a = lv_event_get_param(e);
  if (lv_event_get_code(e) != LV_EVENT_SCROLL_BEGIN || !a)
    return;
  lv_anim_set_duration(a, clamp(LV_ABS(a->end_value - a->start_value) * 3 / 10,
                                48, 180));
  lv_anim_set_path_cb(a, soy_ease_out);
}
static void page_event(lv_event_t *e) {
  lv_event_code_t code = lv_event_get_code(e);
  pace_scroll(e);
  if (code == LV_EVENT_SCROLL_BEGIN || code == LV_EVENT_SCROLL_END) {
    for (int i = 0; i < count; i++) {
      if (!page_images[i])
        continue;
      int cached = code == LV_EVENT_SCROLL_BEGIN && !page_dirty[i];
      lv_obj_set_hidden(page_images[i], !cached);
      lv_obj_set_style_bg_opa(views[i].page,
                              cached ? LV_OPA_TRANSP : LV_OPA_COVER, 0);
      /* Two adjacent pages each cover only part of the invalidated area.
       * Suppress painting the live content behind their snapshots explicitly.
       * Opacity leaves native hit testing and the captured scroll target alive.
       */
      lv_obj_set_style_opa(views[i].body, cached ? LV_OPA_TRANSP : LV_OPA_COVER,
                           0);
      lv_obj_set_style_opa(page_headers[i],
                           cached ? LV_OPA_TRANSP : LV_OPA_COVER, 0);
    }
  }
  if (code == LV_EVENT_SCROLL_END)
    note_scene();
  if (code != LV_EVENT_SCROLL)
    return;
  int next = clamp((lv_obj_get_scroll_x(pager) + W / 2) / W, 0, count - 1);
  if (next != current) {
    current = next;
    update_dots();
  }
}
/* Reading position and text size per scene survive a reboot: Soy keeps
 * /run/soy/positions current, the laptop's follower copies it, and the boot
 * pass puts it back before Soy starts. One "id scroll zoom" line a scene. */
static double positions_due; /* when to rewrite the file; 0 when clean */
static void mark_positions(void) {
  if (!positions_due)
    positions_due = now() + 2;
}
static void load_positions(void) {
  char p[600], id[48];
  int scroll, zoom;
  path(p, sizeof p, rundir, "positions");
  FILE *f = fopen(p, "re");
  if (!f)
    return;
  while (fscanf(f, "%47s %d %d", id, &scroll, &zoom) == 3)
    for (int i = 0; i < count; i++)
      if (!strcmp(scenes[i].id, id)) {
        scenes[i].scroll = scroll > 0 ? scroll : 0;
        scenes[i].zoom = clamp(zoom, 0, 4);
      }
  fclose(f);
}
static void save_positions(void) {
  char p[600], tmp[620];
  path(p, sizeof p, rundir, "positions");
  snprintf(tmp, sizeof tmp, "%s.tmp", p);
  FILE *f = fopen(tmp, "we");
  positions_due = 0;
  if (!f)
    return;
  for (int i = 0; i < count; i++)
    fprintf(f, "%s %d %d\n", scenes[i].id, scenes[i].scroll, scenes[i].zoom);
  if (!fclose(f))
    rename(tmp, p);
}
static void body_event(lv_event_t *e) {
  int index = (int)(intptr_t)lv_event_get_user_data(e);
  lv_event_code_t code = lv_event_get_code(e);
  pace_scroll(e);
  if (code == LV_EVENT_SCROLL &&
      lv_event_get_target_obj(e) == views[index].body) {
    scenes[index].scroll = lv_obj_get_scroll_y(views[index].body);
    invalidate_page(index);
    mark_positions();
  }
  if (multi_latched || sheet || index != current || press_stopped_motion)
    return;
  if (code == LV_EVENT_DOUBLE_CLICKED) {
    zoom_pending = views[index].zoom == 1 ? 3 : 1;
    zoom_anchor = pointer_point.y;
    tap_events++;
  } else if (code == LV_EVENT_LONG_PRESSED) {
    open_sheet(3, 0);
    tap_events++;
  }
}
static void nav_event(lv_event_t *e) {
  if (multi_latched)
    return;
  if (lv_event_get_code(e) == LV_EVENT_SHORT_CLICKED) {
    go(current + (intptr_t)lv_event_get_user_data(e), 1);
    tap_events++;
  } else if (lv_event_get_code(e) == LV_EVENT_LONG_PRESSED) {
    open_sheet(2, 0);
    tap_events++;
  }
}
static void create_body(int i) {
  View *v = &views[i];
  v->body = lv_obj_create(v->page);
  flat(v->body);
  lv_obj_set_pos(v->body, 0, TOP);
  lv_obj_set_size(v->body, W, BOTTOM - TOP);
  lv_obj_set_scroll_dir(v->body, LV_DIR_VER);
  lv_obj_set_scroll_chain_hor(v->body, true);
  lv_obj_set_scroll_chain_ver(v->body, false);
  lv_obj_set_scroll_elastic(v->body, true);
  lv_obj_set_scroll_momentum(v->body, true);
  lv_obj_set_scrollbar_mode(v->body, LV_SCROLLBAR_MODE_ACTIVE);
  lv_obj_set_style_width(v->body, 3, LV_PART_SCROLLBAR);
  lv_obj_set_style_pad_right(v->body, 9, LV_PART_SCROLLBAR);
  lv_obj_set_style_bg_color(v->body, color(scenes[i].accent),
                            LV_PART_SCROLLBAR);
  lv_obj_set_style_bg_opa(v->body, LV_OPA_COVER, LV_PART_SCROLLBAR);
  lv_obj_add_event_cb(v->body, body_event, LV_EVENT_ALL, (void *)(intptr_t)i);
}
/* The sheet backdrop, the card snapshot (sized for the tallest sheet) and
 * the pinch preview are allocated and touched once, before scene layouts
 * claim the cache budget. A fresh 2.4 MB allocation page-faults on a
 * gesture's first frame, and with a full budget a sheet redrew its live
 * controls every frame and a pinch showed no preview at all. */
static lv_draw_buf_t *backdrop, *card, *pinch_buf;
static void reserve_gesture_buffers(void) {
  size_t viewport = (size_t)W * (BOTTOM - TOP) * 4;
  if (!pinch_buf && cache_bytes + viewport <= CACHE_LIMIT) {
    pinch_buf = lv_draw_buf_create(W, BOTTOM - TOP, LV_COLOR_FORMAT_XRGB8888, W * 4);
    if (pinch_buf) {
      memset(pinch_buf->data, 0, viewport);
      cache_bytes += pinch_buf->data_size;
    }
  }
  if (!backdrop && cache_bytes + PIXEL_BYTES < CACHE_LIMIT) {
    backdrop = lv_draw_buf_create(W, H, LV_COLOR_FORMAT_XRGB8888, W * 4);
    if (backdrop) {
      memset(backdrop->data, 0, PIXEL_BYTES);
      cache_bytes += backdrop->data_size;
    }
  }
  if (!card && cache_bytes + (size_t)W * 800 * 4 < CACHE_LIMIT) {
    card = lv_draw_buf_create(W, 800, LV_COLOR_FORMAT_XRGB8888, W * 4);
    if (card) {
      memset(card->data, 0, (size_t)W * 800 * 4);
      cache_bytes += card->data_size;
    }
  }
}
static void build_pages(void) {
  reserve_gesture_buffers();
  end_preview(0);
  if (sheet)
    close_sheet();
  lv_indev_reset(pointer, NULL);
  if (pager)
    lv_obj_delete(pager);
  memset(page_images, 0, sizeof page_images);
  memset(page_headers, 0, sizeof page_headers);
  memset(page_dirty, 0, sizeof page_dirty);
  if (nav)
    lv_obj_delete(nav);
  for (int i = 0; i < NS; i++) {
    free_blocks(&views[i]);
    for (int z = 0; z < 5; z++) {
      free_blocks(&prepared[i][z]);
      memset(&prepared[i][z], 0, sizeof(View));
    }
  }
  pager = lv_obj_create(lv_screen_active());
  flat(pager);
  lv_obj_set_size(pager, W, 884);
  lv_obj_set_scroll_dir(pager, LV_DIR_HOR);
  lv_obj_set_scroll_snap_x(pager, LV_SCROLL_SNAP_START);
  lv_obj_set_scroll_one(pager, true);
  lv_obj_set_scroll_elastic(pager, true);
  lv_obj_set_scroll_momentum(pager, true);
  lv_obj_add_event_cb(pager, page_event, LV_EVENT_ALL, NULL);
  for (int i = 0; i < count; i++) {
    View *v = &views[i];
    v->zoom = clamp(scenes[i].zoom, 0, 4);
    v->page = lv_obj_create(pager);
    flat(v->page);
    lv_obj_set_pos(v->page, i * W, 0);
    lv_obj_set_size(v->page, W, 884);
    lv_obj_set_scrollable(v->page, false);
    lv_obj_set_snappable(v->page, true);
    page_headers[i] = label(v->page, scenes[i].label, 1, MUTED, 34, 30, 572);
    create_body(i);
    int scroll = scenes[i].scroll;
    build_body(i);
    lv_obj_scroll_to_y(v->body, scroll, LV_ANIM_OFF);
    /* Prepare bounded, immutable documents before the first displayed frame.
     * Pinch release then swaps a complete layout instead of rasterizing the
     * entire document on the input thread. Oversized/live documents retain the
     * bounded fallback and remain subject to the same failing performance gate.
     */
    /* Leave room for every page's swipe snapshot (prepare_page). */
    if (!v->live_count && !strstr(scenes[i].body, "{{") && v->nblocks <= 128 &&
        strlen(scenes[i].body) <= 16384 &&
        (size_t)v->height * W * 4 * 6 + cache_bytes +
                (size_t)count * W * 884 * 4 <
            CACHE_LIMIT) {
      View initial = *v;
      for (int z = 0; z < 5; z++) {
        if (z == initial.zoom)
          continue;
        *v = (View){.page = initial.page, .zoom = z};
        create_body(i);
        build_body(i);
        lv_obj_set_hidden(v->body, true);
        prepared[i][z] = *v;
      }
      *v = initial;
      scenes[i].height = v->height;
    }
  }
  nav = lv_obj_create(lv_screen_active());
  flat(nav);
  lv_obj_set_pos(nav, 0, 884);
  lv_obj_set_size(nav, W, 76);
  lv_obj_set_scrollable(nav, false);
  for (int i = 0; i < 2; i++) {
    lv_obj_t *b = lv_obj_create(nav);
    lv_obj_remove_style_all(b);
    lv_obj_set_pos(b, i * W / 2, -12);
    lv_obj_set_size(b, W / 2, 88);
    lv_obj_set_scrollable(b, false);
    lv_obj_add_event_cb(b, nav_event, LV_EVENT_ALL,
                        (void *)(intptr_t)(i ? 1 : -1));
  }
  int visible = count < 9 ? count : 9;
  for (int i = 0; i < visible; i++) {
    dots[i] = lv_obj_create(nav);
    flat(dots[i]);
    lv_obj_set_clickable(dots[i], false);
    lv_obj_set_scrollable(dots[i], false);
  }
  update_dots();
  lv_obj_update_layout(pager);
  lv_obj_scroll_to_x(pager, current * W, LV_ANIM_OFF);
}
static void go(int index, int animate) {
  int next = clamp(index, 0, count - 1);
  current = next;
  update_dots();
  lv_obj_scroll_to_x(pager, next * W, animate ? LV_ANIM_ON : LV_ANIM_OFF);
}
static void resize_text(int index, int level, int anchor) {
  View *v = &views[index];
  level = clamp(level, 0, 4);
  if (level == v->zoom)
    return;
  invalidate_page(index);
  int y = lv_obj_get_scroll_y(v->body) + clamp(anchor - TOP, 0, BOTTOM - TOP);
  int block = 0;
  double fraction = 0;
  for (int j = 0; j < v->nblocks; j++)
    if (lv_obj_get_y(v->blocks[j]) <= y)
      block = j;
  if (v->nblocks)
    fraction = (double)(y - lv_obj_get_y(v->blocks[block])) /
               lv_obj_get_height(v->blocks[block]);
  if (prepared[index][level].body) {
    lv_obj_set_hidden(v->body, true);
    prepared[index][v->zoom] = *v;
    *v = prepared[index][level];
    memset(&prepared[index][level], 0, sizeof(View));
    lv_obj_set_hidden(v->body, false);
    scenes[index].height = v->height;
    lv_obj_update_layout(v->body);
  } else {
    v->zoom = level;
    build_body(index);
  }
  scenes[index].zoom = level;
  mark_positions();
  note("\"e\":\"zoom\",\"scene\":\"%s\",\"font_px\":%d", scenes[index].id,
       body_sizes[level]);
  if (block < v->nblocks)
    y = lv_obj_get_y(v->blocks[block]) +
        (int)(fraction * lv_obj_get_height(v->blocks[block]));
  lv_obj_scroll_to_y(v->body,
                     clamp(y - clamp(anchor - TOP, 0, BOTTOM - TOP), 0,
                           scenes[index].height > BOTTOM - TOP
                               ? scenes[index].height - (BOTTOM - TOP)
                               : 0),
                     LV_ANIM_OFF);
}
static int sheet_open_amount(void) {
  if (!sheet)
    return 0;
  int scroll = lv_obj_get_scroll_y(sheet);
  return clamp(sheet_kind == 1 ? sheet_height - scroll : scroll, 0,
               sheet_height);
}
static void sheet_event(lv_event_t *e) {
  if (sheet_initializing || !sheet)
    return;
  lv_event_code_t c = lv_event_get_code(e);
  pace_scroll(e);
  if (sheet_picture &&
      (c == LV_EVENT_SCROLL_BEGIN || c == LV_EVENT_SCROLL_END)) {
    int moving = c == LV_EVENT_SCROLL_BEGIN;
    lv_obj_set_style_opa(sheet_card, moving ? LV_OPA_TRANSP : LV_OPA_COVER, 0);
    lv_obj_set_hidden(sheet_picture, !moving);
  }
  if (c == LV_EVENT_SCROLL_END && sheet_open_amount() < 4 && !contacts_active)
    close_pending = 1;
  if (c == LV_EVENT_SHORT_CLICKED && lv_event_get_target_obj(e) == sheet)
    close_pending = 1;
}
static void button_event(lv_event_t *e) {
  if (multi_latched)
    return;
  intptr_t action = (intptr_t)lv_event_get_user_data(e);
  tap_events++;
  if (action >= 0) {
    go((int)action, 0);
    close_pending = 1;
  } else if (action == -1) {
    zoom_pending = views[current].zoom - 1;
    zoom_anchor = H / 2;
  } else if (action == -2) {
    zoom_pending = views[current].zoom + 1;
    zoom_anchor = H / 2;
  } else if (action == -3) {
    lv_obj_scroll_to_y(views[current].body, 0, LV_ANIM_ON);
    close_pending = 1;
  }
}
static void button(lv_obj_t *parent, const char *txt, int x, int y, int w,
                   intptr_t action) {
  lv_obj_t *b = lv_obj_create(parent);
  flat(b);
  lv_obj_set_pos(b, x, y);
  lv_obj_set_size(b, w, 96);
  lv_obj_set_scrollable(b, false);
  lv_obj_set_style_bg_color(b, color(0x101a14), 0);
  lv_obj_set_style_bg_color(b, color(LINE), LV_STATE_PRESSED);
  label(b, txt, 1, INK, 20, 22, w - 40);
  lv_obj_add_event_cb(b, button_event, LV_EVENT_SHORT_CLICKED, (void *)action);
}
static void invalidate_sheet_picture(lv_event_t *e) {
  (void)e;
  if (sheet_picture) {
    lv_obj_delete(sheet_picture);
    sheet_picture = NULL;
    lv_obj_set_style_opa(sheet_card, LV_OPA_COVER, 0);
  }
}
static void outside_sheet(lv_event_t *e) {
  (void)e;
  close_pending = 1;
}
static void open_sheet(int kind, int from_edge) {
  if (sheet)
    return;
  sheet_kind = kind;
  sheet_height = kind == 1   ? 480
                 : kind == 2 ? clamp(100 + count * 100, 300, 800)
                             : 420;
  sheet_initializing = 1;
  close_pending = 0;
  /* A modal freezes its underlay. An opaque object also lets LVGL cull the
   * covered page tree; a transparent image alone does not establish cover. */
  if (backdrop) {
    lv_draw_buf_t *buf = backdrop;
    {
      memcpy(buf->data, pixels, PIXEL_BYTES);
      /* One fixed dimmed backdrop, rather than blending the whole display
       * for every pixel of panel movement. Keep the hot path to opaque copies.
       */
      soy_snapshot_dim(buf, LV_OPA_60);
      lv_draw_buf_set_flag(buf, LV_IMAGE_FLAGS_USER1);
      sheet_backdrop = lv_image_create(lv_screen_active());
      lv_image_set_src(sheet_backdrop, buf);
      lv_obj_set_style_bg_opa(sheet_backdrop, LV_OPA_COVER, 0);
      lv_obj_set_clickable(sheet_backdrop, false);
      /* Reusing the buffer is safe: LV_CACHE_DEF_SIZE is 0, so LVGL keeps
       * no decoded copy keyed by this pointer. */
    }
  }
  sheet_shield = lv_obj_create(lv_screen_active());
  flat(sheet_shield);
  lv_obj_set_size(sheet_shield, W, H);
  lv_obj_set_style_bg_opa(sheet_shield, LV_OPA_TRANSP, 0);
  lv_obj_set_scrollable(sheet_shield, false);
  lv_obj_add_event_cb(sheet_shield, outside_sheet, LV_EVENT_SHORT_CLICKED,
                      NULL);
  sheet = lv_obj_create(lv_screen_active());
  flat(sheet);
  /* LVGL invalidates a scrolled container's bounds. Keep them to the card's
   * travel band, with a separate static target for outside taps. */
  lv_obj_set_pos(sheet, 0, kind == 1 ? 0 : H - sheet_height);
  lv_obj_set_size(sheet, W, sheet_height);
  lv_obj_set_style_bg_color(sheet, color(0), 0);
  lv_obj_set_style_bg_opa(sheet, LV_OPA_TRANSP, 0);
  lv_obj_set_scroll_dir(sheet, LV_DIR_VER);
  lv_obj_set_scroll_elastic(sheet, false);
  lv_obj_set_scroll_momentum(sheet, true);
  lv_obj_set_scroll_one(sheet, true);
  lv_obj_set_scroll_snap_y(sheet, LV_SCROLL_SNAP_START);
  for (int i = 0; i < 2; i++) {
    lv_obj_t *a = lv_obj_create(sheet);
    lv_obj_remove_style_all(a);
    lv_obj_set_pos(a, 0, i * sheet_height);
    lv_obj_set_size(a, 1, 1);
    lv_obj_set_snappable(a, true);
    lv_obj_set_clickable(a, false);
  }
  lv_obj_t *extent = lv_obj_create(sheet);
  lv_obj_remove_style_all(extent);
  lv_obj_set_pos(extent, 0, 2 * sheet_height - 1);
  lv_obj_set_size(extent, 1, 1);
  lv_obj_set_clickable(extent, false);
  lv_obj_set_snappable(extent, false);
  sheet_card = lv_obj_create(sheet);
  flat(sheet_card);
  lv_obj_set_pos(sheet_card, 0, kind == 1 ? 0 : sheet_height);
  lv_obj_set_size(sheet_card, W, sheet_height);
  lv_obj_set_style_bg_color(sheet_card, color(0x101a14), 0);
  lv_obj_set_scrollable(sheet_card, false);
  lv_obj_set_snappable(sheet_card, false);
  label(sheet_card,
        kind == 1   ? "Device"
        : kind == 2 ? "Scenes"
                    : "Text",
        2, INK, 34, 24, 572);
  if (kind == 1) {
    char txt[256], value[128];
    binding("battery.percent", value, sizeof value);
    snprintf(txt, sizeof txt, "Battery  %s\nWi-Fi  %s\nLink  %s", value,
             wifi_state, !strcmp(net_name, "usb0") ? "USB" : net_name);
    label(sheet_card, txt, 1, INK, 34, 126, 572);
  } else if (kind == 2) {
    lv_obj_t *list = lv_obj_create(sheet_card);
    flat(list);
    lv_obj_set_pos(list, 0, 100);
    lv_obj_set_size(list, W, sheet_height - 100);
    lv_obj_set_scroll_dir(list, LV_DIR_VER);
    lv_obj_set_scroll_chain_ver(list, true);
    lv_obj_add_event_cb(list, invalidate_sheet_picture, LV_EVENT_SCROLL, NULL);
    for (int i = 0; i < count; i++)
      button(list, scenes[i].label, 14, i * 100, 612, i);
  } else {
    button(sheet_card, "A−", 34, 124, 270, -1);
    button(sheet_card, "A+", 336, 124, 270, -2);
    button(sheet_card, "Top", 34, 238, 572, -3);
  }
  lv_obj_t *handle = lv_obj_create(sheet_card);
  flat(handle);
  lv_obj_set_style_bg_color(handle, color(MUTED), 0);
  lv_obj_set_pos(handle, W / 2 - 32, kind == 1 ? sheet_height - 18 : 8);
  lv_obj_set_size(handle, 64, 4);
  lv_obj_set_clickable(handle, false);
  lv_obj_update_layout(sheet_card);
  if (card && lv_snapshot_reshape_draw_buf(sheet_card, card) == LV_RESULT_OK &&
      lv_snapshot_take_to_draw_buf(sheet_card, LV_COLOR_FORMAT_XRGB8888, card) ==
          LV_RESULT_OK) {
    lv_draw_buf_t *buf = card;
    {
      lv_draw_buf_set_flag(buf, LV_IMAGE_FLAGS_USER1);
      sheet_picture = lv_image_create(sheet);
      lv_image_set_src(sheet_picture, buf);
      lv_obj_set_pos(sheet_picture, 0, kind == 1 ? 0 : sheet_height);
      lv_obj_set_clickable(sheet_picture, false);
      lv_obj_set_snappable(sheet_picture, false);
      lv_obj_set_hidden(sheet_picture, true);
    }
  }
  lv_obj_add_event_cb(sheet, sheet_event, LV_EVENT_ALL, NULL);
  lv_obj_update_layout(sheet);
  int closed = kind == 1 ? sheet_height : 0,
      opened = kind == 1 ? 0 : sheet_height;
  lv_obj_scroll_to_y(sheet, closed, LV_ANIM_OFF);
  sheet_initializing = 0;
  if (!from_edge)
    lv_obj_scroll_to_y(sheet, opened, LV_ANIM_ON);
}
static void close_sheet(void) {
  if (!sheet)
    return;
  lv_indev_reset(pointer, NULL);
  lv_obj_delete(sheet);
  lv_obj_delete(sheet_shield);
  sheet_shield = NULL;
  if (sheet_backdrop) {
    lv_obj_delete(sheet_backdrop);
    sheet_backdrop = NULL;
  }
  sheet = NULL;
  sheet_card = NULL;
  sheet_picture = NULL;
  sheet_kind = 0;
  close_pending = 0;
}
static void cancel_motion(void) {
  lv_indev_reset(pointer, NULL);
  lv_obj_stop_scroll_anim(pager);
  go(current, 0);
  for (int i = 0; i < count; i++) {
    lv_obj_stop_scroll_anim(views[i].body);
    int max = scenes[i].height - (BOTTOM - TOP);
    if (max < 0)
      max = 0;
    lv_obj_scroll_to_y(views[i].body,
                       clamp(lv_obj_get_scroll_y(views[i].body), 0, max),
                       LV_ANIM_OFF);
  }
}
static void end_preview(int commit) {
  if (commit && pinch_index == current) {
    /* Keep the preview until the same refresh can show the new layout. */
    zoom_pending = pinch_level;
    return;
  }
  if (pinch_layer) {
    lv_obj_delete(pinch_layer);
    pinch_layer = pinch_preview = NULL;
  }
  if (pinch_image) {
    soy_pinch_draw_source(NULL);
    pinch_image = NULL; /* The reserved buffer stays for the next pinch. */
  }
  preview_scale = 1;
}
static void set_backlight(int on) {
  glob_t g = {0};
  /* Only the phone's PMU backlight; never a desktop panel during host tests. */
  if (headless || glob("/sys/class/backlight/pmu-backlight/bl_power", 0, NULL, &g)) {
    globfree(&g);
    backlight_state = -1;
    return;
  }
  int ok = 0;
  for (size_t i = 0; i < g.gl_pathc; i++) {
    int fd = open(g.gl_pathv[i], O_WRONLY | O_CLOEXEC);
    /* FB_BLANK_UNBLANK 0, FB_BLANK_POWERDOWN 4. */
    if (fd >= 0) {
      ok |= write(fd, on ? "0\n" : "4\n", 2) == 2;
      close(fd);
    }
  }
  globfree(&g);
  backlight_state = ok ? on : -1;
}
/* Physical buttons (gpio-keys-polled): Home and Power wake the screen, Power
 * also sleeps it, and the volume buttons turn pages (turn_page). */
static void open_keys(void) {
  glob_t g = {0};
  if (keyfd >= 0 || glob("/dev/input/event*", 0, NULL, &g)) {
    globfree(&g);
    return;
  }
  for (size_t i = 0; i < g.gl_pathc && keyfd < 0; i++) {
    char name[64] = "";
    int fd = open(g.gl_pathv[i], O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0)
      continue;
    ioctl(fd, EVIOCGNAME(sizeof name - 1), name);
    /* The N90 buttons only; a host keyboard's power key is not ours. */
    if (!headless && !strcmp(name, "gpio-keys-polled"))
      keyfd = fd;
    else
      close(fd);
  }
  globfree(&g);
}
static void wake_display(const char *why);
static void sleep_display(const char *why);
/* The volume buttons turn the page: down shows the next screenful and up
 * the one before, each keeping the last two lines in view. Past either end
 * of a scene they move to the neighbouring scene, as a book would. Reading
 * then needs one thumb, and no glass: gloves, rain, a camera in the other
 * hand. */
static void turn_page(int dir) {
  View *v = &views[current];
  int32_t y = lv_obj_get_scroll_y(v->body),
          end = y + lv_obj_get_scroll_bottom(v->body),
          step = BOTTOM - TOP - 2 * faces[body_faces[v->zoom]].line_height;
  if (sheet || pointer_pressed || multi_latched || count == 0)
    return;
  if (dir > 0 ? y >= end : y <= 0) {
    if (current + dir >= 0 && current + dir < count)
      go(current + dir, 1);
    return;
  }
  lv_obj_scroll_to_y(v->body, clamp(y + dir * step, 0, end), LV_ANIM_ON);
}
static void read_keys(void) {
  struct input_event e[16];
  ssize_t n;
  while ((n = read(keyfd, e, sizeof e)) > 0)
    for (size_t i = 0; i < (size_t)n / sizeof e[0]; i++) {
      if (e[i].type != EV_KEY || e[i].value != 1)
        continue;
      if (e[i].code == KEY_POWER && !blank_screen)
        sleep_display("power");
      else if (e[i].code == KEY_POWER || e[i].code == KEY_HOME)
        wake_display(e[i].code == KEY_POWER ? "power" : "home");
      else if ((e[i].code == KEY_VOLUMEDOWN || e[i].code == KEY_VOLUMEUP) &&
               !blank_screen) {
        lv_display_trigger_activity(display);
        turn_page(e[i].code == KEY_VOLUMEDOWN ? 1 : -1);
      }
    }
  if (n < 0 && errno != EAGAIN) {
    close(keyfd);
    keyfd = -1;
  }
}
/* /run/soy/blanked tells n90-touch to poll the controller less often: with
 * the screen off a touch only has to wake it. */
static void mark_blanked(int on) {
  char flag[600];
  path(flag, sizeof flag, rundir, "blanked");
  if (on)
    close(open(flag, O_WRONLY | O_CREAT | O_CLOEXEC, 0644));
  else
    unlink(flag);
}
static void wake_display(const char *why) {
  lv_display_trigger_activity(display);
  if (!blank_screen)
    return;
  note("\"e\":\"wake\",\"why\":\"%s\"", why);
  lv_obj_delete(blank_screen);
  blank_screen = NULL;
  mark_blanked(0);
  lv_timer_resume(lv_display_get_refr_timer(display));
  lv_timer_ready(lv_display_get_refr_timer(display));
  lv_obj_invalidate(lv_screen_active());
  /* Light the panel only after the restored scene is in the buffer. */
  lv_refr_now(display);
  if (backlight_state == 0)
    set_backlight(1);
}
static void sleep_display(const char *why) {
  if (blank_screen)
    return;
  note("\"e\":\"sleep\",\"why\":\"%s\",\"scene\":\"%s\",\"scroll\":%d,"
       "\"height\":%d",
       why, scenes[current].id, scenes[current].scroll, scenes[current].height);
  end_preview(0);
  zoom_pending = -1;
  cancel_motion();
  if (sheet)
    close_sheet();
  wake_contact = contacts_active != 0;
  pointer_pressed = multi_latched = 0;
  primary = -1;
  lv_indev_touch_data_t released[SOY_CONTACTS];
  for (int i = 0; i < SOY_CONTACTS; i++)
    released[i] = (lv_indev_touch_data_t){.id = i, .state = LV_INDEV_STATE_RELEASED};
  lv_indev_gesture_recognizers_update(pointer, released, SOY_CONTACTS);
  /* Black pixels and paused rendering, then the PMU backlight off when the
   * kernel exposes one. This is not panel power-off or system suspend. */
  blank_screen = lv_obj_create(lv_layer_sys());
  flat(blank_screen);
  lv_obj_set_style_bg_color(blank_screen, lv_color_black(), 0);
  lv_obj_set_size(blank_screen, W, H);
  lv_obj_set_scrollable(blank_screen, false);
  lv_refr_now(display);
  lv_timer_pause(lv_display_get_refr_timer(display));
  set_backlight(0);
  mark_blanked(1);
}
static int set_idle_timeout(const char *s) {
  if (!*s || strspn(s, "0123456789") != strlen(s))
    return -1;
  char *end;
  errno = 0;
  unsigned long seconds = strtoul(s, &end, 10);
  if (errno || *end || seconds > 86400)
    return -1;
  idle_seconds = seconds;
  return 0;
}
static void read_pointer(lv_indev_t *indev, lv_indev_data_t *data) {
  double began = now();
  static unsigned batch;
  SoyContacts f;
  int fresh = soy_input_next(&f);
  if (fresh) {
    input_sequence = f.sequence;
    input_time = now();
    if (f.active && !f.cancel) {
      lv_display_trigger_activity(display);
      if (blank_screen && !wake_contact) {
        wake_display("touch");
        wake_contact = 1;
      }
    }
    /* The entire waking contact sequence belongs to wake, including a second
     * finger. It must not tap a control, scroll, or enter a pinch recognizer. */
    if (blank_screen || wake_contact) {
      contacts_active = f.active;
      if (!f.active || f.cancel)
        wake_contact = 0;
      data->state = LV_INDEV_STATE_RELEASED;
      data->point = pointer_point;
      data->continue_reading = ++batch < 64;
      if (!data->continue_reading)
        batch = 0;
      input_time = 0;
      return;
    }
    if (f.cancel) {
      end_preview(0);
      cancel_motion();
      if (sheet)
        close_pending = 1;
      pointer_pressed = contacts_active = multi_latched = 0;
      primary = -1;
      /* Release every recognizer slot after overflow/removal, then reset its
       * state. */
      for (int i = 0; i < SOY_CONTACTS; i++)
        f.touches[i] =
            (lv_indev_touch_data_t){.id = i, .state = LV_INDEV_STATE_RELEASED};
      f.count = SOY_CONTACTS;
    }
    lv_indev_gesture_recognizers_update(indev, f.touches, f.count);
    lv_indev_gesture_recognizers_set_data(indev, data);
    lv_indev_gesture_recognizer_t *pinch =
        data->gesture_data[LV_INDEV_GESTURE_PINCH];
    if (f.active >= 2 && !multi_latched) {
      multi_latched = 1;
      multi_canceled = 0;
      pinch_base = views[current].zoom;
      pinch_level = pinch_base;
      pinch_index = current;
      cancel_motion();
      if (!sheet && pinch_buf) {
        Frame *last = frames ? &trace[(frames - 1) % TRACE_FRAMES] : NULL;
        /* The settled viewport is already laid out and rendered. Copy those
         * exact pixels when they match the current view; interruption during
         * a page/reading animation still takes a fresh LVGL snapshot. */
        if (last && !page_dirty[current] && last->scene == current &&
            last->page == current * W &&
            last->scroll == lv_obj_get_scroll_y(views[current].body) &&
            !last->panel && last->scale == 1) {
          memcpy(pinch_buf->data, pixels + TOP * W,
                 (size_t)W * (BOTTOM - TOP) * 4);
          pinch_image = pinch_buf;
        } else if (lv_snapshot_reshape_draw_buf(views[current].body, pinch_buf) ==
                       LV_RESULT_OK &&
                   lv_snapshot_take_to_draw_buf(views[current].body,
                                                LV_COLOR_FORMAT_XRGB8888,
                                                pinch_buf) == LV_RESULT_OK) {
          pinch_image = pinch_buf;
        }
        if (pinch_image) {
          soy_pinch_draw_source(NULL);
          pinch_layer = lv_obj_create(views[current].page);
          flat(pinch_layer);
          lv_obj_set_pos(pinch_layer, 0, TOP);
          lv_obj_set_size(pinch_layer, W, BOTTOM - TOP);
          lv_obj_set_scrollable(pinch_layer, false);
          pinch_preview = lv_image_create(pinch_layer);
          soy_pinch_draw_source(pinch_image);
          lv_image_set_src(pinch_preview, pinch_image);
          lv_obj_set_pos(pinch_preview, 0, 0);
          lv_obj_set_clickable(pinch_preview, false);
        }
      }
    }
    if (f.active > 2) {
      multi_canceled = 1;
      end_preview(0);
    }
    if (multi_latched && sheet)
      close_pending = 1;
    if (multi_latched && !multi_canceled && pinch &&
        pinch->state == LV_INDEV_GESTURE_STATE_RECOGNIZED && !sheet) {
      float desired = body_sizes[pinch_base] * pinch->scale;
      if (isfinite(desired) && desired > 0) {
        int level = 0;
        for (int i = 1; i < 5; i++)
          if (fabsf(body_sizes[i] - desired) <
              fabsf(body_sizes[level] - desired))
            level = i;
        lv_point_t center;
        lv_indev_get_gesture_center_point(pinch, &center);
        if (pinch_index == current) {
          pinch_level = level;
          zoom_anchor = center.y;
          pinch_events++;
          preview_scale =
              fmaxf(32.f / body_sizes[pinch_base],
                    fminf(54.f / body_sizes[pinch_base], pinch->scale));
          if (pinch_preview) {
            lv_image_set_pivot(pinch_preview, center.x,
                               clamp(center.y - TOP, 0, BOTTOM - TOP));
            lv_image_set_scale(pinch_preview, (uint32_t)(256 * preview_scale));
          }
        }
      }
    }
    if (!f.cancel && !multi_latched) {
      if (!contacts_active && f.active) {
        press_stopped_motion = lv_obj_is_scrolling(pager) ||
                               lv_obj_is_scrolling(views[current].body);
        primary = -1;
        for (int i = 0; i < f.count; i++)
          if (f.touches[i].state == LV_INDEV_STATE_PRESSED) {
            primary = f.touches[i].id;
            pointer_point = f.touches[i].point;
            break;
          }
        if (!sheet && pointer_point.y < 40)
          open_sheet(1, 1);
        else if (!sheet && pointer_point.y >= H - 40)
          open_sheet(2, 1);
      }
      for (int i = 0; i < f.count; i++)
        if (f.touches[i].id == primary) {
          pointer_point = f.touches[i].point;
          pointer_pressed = f.touches[i].state == LV_INDEV_STATE_PRESSED;
        }
    } else
      pointer_pressed = 0;
    contacts_active = f.active;
    if (!f.active) {
      if (multi_latched)
        end_preview(!f.cancel && !multi_canceled);
      pointer_pressed = 0;
      primary = -1;
      multi_latched = 0;
      if (sheet && sheet_open_amount() < 4)
        close_pending = 1;
    }
    /* Gesture product policy above consumes multitouch; don't also treat it as
     * a single pointer click/scroll. The recognizers themselves remain LVGL's.
     */
    memset(data->gesture_type, 0, sizeof data->gesture_type);
    memset(data->gesture_data, 0, sizeof data->gesture_data);
    data->continue_reading = ++batch < 64;
    if (!data->continue_reading)
      batch = 0;
  } else
    batch = 0;
  data->point = pointer_point;
  data->state =
      pointer_pressed ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
  input_work_ms += (now() - began) * 1000;
}
static int capture(const char *file) {
  FILE *f = fopen(file, "wb");
  if (!f)
    return -1;
  fprintf(f, "P6\n640 960\n255\n");
  unsigned char row[W * 3];
  for (int y = 0; y < H; y++) {
    for (int x = 0; x < W; x++) {
      uint32_t c = pixels[y * W + x];
      row[x * 3] = c >> 16;
      row[x * 3 + 1] = c >> 8;
      row[x * 3 + 2] = c;
    }
    if (fwrite(row, 1, sizeof row, f) != sizeof row) {
      fclose(f);
      return -1;
    }
  }
  return fclose(f);
}
static void flush(lv_display_t *d, const lv_area_t *area, uint8_t *p) {
  (void)p;
  if (area->x1 < damage.x1)
    damage.x1 = area->x1;
  if (area->y1 < damage.y1)
    damage.y1 = area->y1;
  if (area->x2 > damage.x2)
    damage.x2 = area->x2;
  if (area->y2 > damage.y2)
    damage.y2 = area->y2;
  if (lv_display_flush_is_last(d)) {
    double transfer_start = now();
    double transfer_cpu_start = thread_cpu_ms();
    if (direct_display) {
      if (soy_display_present(damage.x1, damage.y1, damage.x2 + 1,
                              damage.y2 + 1))
        stopping = 1;
    } else if (fb >= 0) {
      size_t n = (size_t)damage.y1 * W * 4;
      size_t end = (size_t)(damage.y2 + 1) * W * 4;
      while (n < end) {
        ssize_t w = pwrite(fb, (char *)pixels + n, end - n, n);
        if (w < 0 && errno == EINTR)
          continue;
        if (w <= 0) {
          stopping = 1;
          break;
        }
        n += w;
      }
    }
    double t = now(), elapsed = (t - frame_start) * 1000;
    double cpu_end = thread_cpu_ms();
    struct rusage usage = {0};
    getrusage(RUSAGE_THREAD, &usage);
    double transfer = (t - transfer_start) * 1000;
    transfer_sum += transfer;
    if (transfer > transfer_max)
      transfer_max = transfer;
    render_samples[frames % 256] = elapsed;
    frame_times[frames % 256] = t;
    trace[frames % TRACE_FRAMES] =
        (Frame){.start = frame_start,
                .end = t,
                .transfer = transfer,
                .input = input_sequence,
                .scene = current,
                .scroll = lv_obj_get_scroll_y(views[current].body),
                .page = lv_obj_get_scroll_x(pager),
                .panel = sheet_open_amount(),
                .contacts = contacts_active,
                .scale = preview_scale,
                .cpu_end = cpu_end,
                .render_cpu = cpu_end - frame_cpu_start,
                .transfer_cpu = cpu_end - transfer_cpu_start,
                .input_work = input_work_ms,
                .stats_end = stats_end,
                .stats_ms = stats_ms,
                .status_end = status_end,
                .status_ms = status_ms,
                .x1 = damage.x1,
                .y1 = damage.y1,
                .x2 = damage.x2,
                .y2 = damage.y2,
                .voluntary = usage.ru_nvcsw,
                .involuntary = usage.ru_nivcsw};
    trace[frames % TRACE_FRAMES].panel_kind = sheet_kind;
    trace[frames % TRACE_FRAMES].font_px = body_sizes[views[current].zoom];
    input_work_ms = 0;
    frames++;
    render_sum += elapsed;
    if (elapsed > render_max)
      render_max = elapsed;
    if (input_time && t - input_time < 1) {
      double latency = (t - input_time) * 1000;
      if (latency > latency_max)
        latency_max = latency;
      input_time = 0;
    }
  }
  lv_display_flush_ready(d);
}
static void refresh_event(lv_event_t *e) {
  if (lv_event_get_code(e) == LV_EVENT_REFR_START) {
    frame_start = now();
    frame_cpu_start = thread_cpu_ms();
    damage = (lv_area_t){W, H, -1, -1};
  }
}
static void write_trace(void) {
  char file[600];
  path(file, sizeof file, rundir, "frames.csv");
  FILE *f = fopen(file, "w");
  if (!f)
    return;
  fprintf(f, "frame,start_s,end_s,transfer_ms,input,scene,scroll,page,panel,"
             "contacts,scale,cpu_end_ms,render_cpu_ms,transfer_cpu_ms,"
             "input_work_ms,stats_end_s,stats_ms,status_end_s,status_ms,"
             "damage_x1,damage_y1,damage_x2,damage_y2,voluntary_switches,"
             "involuntary_switches,panel_kind,font_px\n");
  unsigned long start = frames > TRACE_FRAMES ? frames - TRACE_FRAMES : 0;
  for (unsigned long i = start; i < frames; i++) {
    Frame *t = &trace[i % TRACE_FRAMES];
    fprintf(f,
            "%lu,%.6f,%.6f,%.3f,%lu,%d,%d,%d,%d,%d,%.4f,"
            "%.3f,%.3f,%.3f,%.3f,%.6f,%.3f,%.6f,%.3f,"
            "%d,%d,%d,%d,%ld,%ld,%d,%d\n",
            i, t->start, t->end, t->transfer, t->input, t->scene, t->scroll,
            t->page, t->panel, t->contacts, t->scale, t->cpu_end, t->render_cpu,
            t->transfer_cpu, t->input_work, t->stats_end, t->stats_ms,
            t->status_end, t->status_ms, t->x1, t->y1, t->x2, t->y2,
            t->voluntary, t->involuntary, t->panel_kind, t->font_px);
  }
  fclose(f);
}
static int compare_double(const void *a, const void *b) {
  double x = *(const double *)a, y = *(const double *)b;
  return (x > y) - (x < y);
}
static void status(void) {
  char p[600], tmp[600];
  path(p, sizeof p, rundir, "status.json");
  path(tmp, sizeof tmp, rundir, "status.new");
  FILE *f = fopen(tmp, "w");
  if (!f)
    return;
  int n = frames < 256 ? frames : 256;
  double sorted[256];
  memcpy(sorted, render_samples, n * sizeof(double));
  qsort(sorted, n, sizeof(double), compare_double);
  fprintf(f,
          "{\"backend\":\"%s\",\"toolkit\":\"LVGL "
          "9.6.0\",\"scene\":\"%s\",\"scroll\":%d,\"page_x\":%d,\"content_"
          "height\":%d,\"font_px\":%d,\"pinch_scale\":%.3f,\"cache_bytes\":%zu,"
          "\"panel\":%d,\"panel_open\":%d,\"count\":%d,\"contacts\":%d,\"input_"
          "devices\":%d,\"virtual_inputs\":%d,\"physical_inputs\":%d,\"evdev_"
          "events\":%lu,\"dropped_events\":%lu,\"input_frames\":%lu,\"pinch_"
          "events\":%lu,\"tap_events\":%lu,\"frames\":%lu,\"render_present_avg_"
          "ms\":%.3f,\"render_present_p95_ms\":%.3f,\"render_present_max_ms\":%"
          ".3f,\"input_present_max_ms\":%.3f,\"transfer_avg_ms\":%.3f,"
          "\"transfer_max_ms\":%.3f,\"scanout_verified\":false,"
          "\"display_state\":\"%s\",\"idle_timeout_s\":%u,"
          "\"inactive_ms\":%u,\"backlight\":\"%s\",\"buttons\":%s,",
          headless         ? "headless"
          : direct_display ? "simpledrm"
                           : "framebuffer",
          scenes[current].id, (int)lv_obj_get_scroll_y(views[current].body),
          (int)lv_obj_get_scroll_x(pager), scenes[current].height,
          body_sizes[views[current].zoom], preview_scale, cache_bytes,
          sheet_kind, sheet_open_amount(), count, contacts_active,
          soy_input_devices(0), soy_input_devices(1),
          soy_input_devices(0) - soy_input_devices(1), soy_input_events(),
          soy_input_drops(), input_sequence, pinch_events, tap_events, frames,
          frames ? render_sum / frames : 0, n ? sorted[(n - 1) * 95 / 100] : 0,
          render_max, latency_max, frames ? transfer_sum / frames : 0,
          transfer_max, blank_screen ? "blanked" : "awake", idle_seconds,
          lv_display_get_inactive_time(display),
          backlight_state < 0 ? "unavailable" : backlight_state ? "on" : "off",
          keyfd >= 0 ? "true" : "false");
  fputs("\"scenes\":[", f);
  for (int i = 0; i < count; i++)
    fprintf(f, "%s\"%s\"", i ? "," : "", scenes[i].id);
  fprintf(f, "],\"bundle_loads\":%u,\"bundle_failures\":%u,"
             "\"bundle_error\":\"%s\"}\n",
          bundle_loads, bundle_failures, bundle_error);
  fclose(f);
  rename(tmp, p);
}
static void command(char *s) {
  if (!strcmp(s, "sleep")) {
    sleep_display("remote");
    return;
  }
  if (!strcmp(s, "wake")) {
    wake_display("remote");
    return;
  }
  if (!strncmp(s, "idle ", 5)) {
    if (set_idle_timeout(s + 5))
      fprintf(stderr, "Idle timeout must be 0..86400 seconds\n");
    return;
  }
  if (!strcmp(s, "next") || !strcmp(s, "prev") ||
      !strncmp(s, "goto ", 5) || !strncmp(s, "scroll ", 7))
    wake_display("remote");
  if (!strcmp(s, "next"))
    go(current + 1, 1);
  else if (!strcmp(s, "prev"))
    go(current - 1, 1);
  else if (!strncmp(s, "goto ", 5)) {
    for (int i = 0; i < count; i++)
      if (!strcmp(s + 5, scenes[i].id))
        go(i, 1);
  } else if (!strncmp(s, "scroll ", 7)) {
    int max = scenes[current].height - (BOTTOM - TOP);
    if (max < 0)
      max = 0;
    int to = clamp(lv_obj_get_scroll_y(views[current].body) +
                       clamp(atoi(s + 7), -9600, 9600),
                   0, max);
    lv_obj_scroll_to_y(views[current].body, to, LV_ANIM_ON);
  } else if (!strcmp(s, "reload"))
    reload_requested = 1;
  else if (!strcmp(s, "trace"))
    write_trace();
  else if (!strcmp(s, "capture")) {
    char p[600];
    path(p, sizeof p, rundir, "frame.ppm");
    if (!blank_screen)
      lv_refr_now(display);
    capture(p);
  } else if (!strcmp(s, "quit"))
    stopping = 1;
}
static void graphics_console(void) {
  ttyfd = open("/dev/tty0", O_RDWR | O_CLOEXEC);
  if (ttyfd >= 0 && !ioctl(ttyfd, KDGETMODE, &tty_mode))
    ioctl(ttyfd, KDSETMODE, KD_GRAPHICS);
}
static int open_display(void) {
  pixels = soy_display_open();
  if (pixels) {
    direct_display = 1;
    graphics_console();
    return 0;
  }
  pixels = fallback_pixels;
  fb = open("/dev/fb0", O_RDWR | O_CLOEXEC);
  if (fb < 0)
    return -1;
  struct fb_fix_screeninfo fix;
  struct fb_var_screeninfo v;
  if (ioctl(fb, FBIOGET_FSCREENINFO, &fix) ||
      ioctl(fb, FBIOGET_VSCREENINFO, &v) || v.xres != W || v.yres != H ||
      v.bits_per_pixel != 32 || fix.line_length != W * 4 ||
      v.red.offset != 16 || v.green.offset != 8 || v.blue.offset != 0 ||
      v.xoffset || v.yoffset) {
    errno = ENOTSUP;
    return -1;
  }
  graphics_console();
  return 0;
}
int main(int argc, char **argv) {
  int check = 0, render = 0;
  const char *initial = NULL, *output = NULL;
  for (int i = 1; i < argc; i++) {
    if (!strcmp(argv[i], "--headless"))
      headless = 1;
    else if (!strcmp(argv[i], "--check"))
      check = 1;
    else if (!strcmp(argv[i], "--idle-seconds") && i + 1 < argc) {
      if (set_idle_timeout(argv[++i])) {
        fprintf(stderr, "Idle timeout must be 0..86400 seconds\n");
        return 2;
      }
    } else if (!strcmp(argv[i], "--render") && i + 1 < argc) {
      render = headless = 1;
      output = argv[++i];
    } else if (!strcmp(argv[i], "--scene") && i + 1 < argc)
      initial = argv[++i];
    else if (!strcmp(argv[i], "--assets") && i + 1 < argc)
      snprintf(assetdir, sizeof assetdir, "%s", argv[++i]);
    else if (!strcmp(argv[i], "--scenes") && i + 1 < argc)
      snprintf(scenedir, sizeof scenedir, "%s", argv[++i]);
    else if (!strcmp(argv[i], "--run") && i + 1 < argc)
      snprintf(rundir, sizeof rundir, "%s", argv[++i]);
    else {
      fprintf(stderr, "Unknown or incomplete option: %s\n", argv[i]);
      return 2;
    }
  }
  if (init_fonts() || load_scenes()) {
    fprintf(stderr, "Invalid fonts or scene bundle\n");
    return 2;
  }
  load_positions();
  if (initial) {
    int found = 0;
    for (int i = 0; i < count; i++)
      if (!strcmp(initial, scenes[i].id)) {
        current = i;
        found = 1;
      }
    if (!found) {
      fprintf(stderr, "Scene '%s' is not in the bundle\n", initial);
      return 2;
    }
  }
  if (check) {
    printf("Valid bundle: %d scenes; LVGL touch runtime\n", count);
    return 0;
  }
  if (!render && mkdir(rundir, 0700) && errno != EEXIST)
    return 2;
  char p[600];
  int lockfd = -1;
  if (!render) {
    path(p, sizeof p, rundir, "renderer.lock");
    lockfd = open(p, O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (lockfd < 0 || flock(lockfd, LOCK_EX | LOCK_NB)) {
      fprintf(stderr, "Renderer already running\n");
      return 2;
    }
  }
  if (!headless && open_display()) {
    perror("Framebuffer unavailable or unsupported");
    return 2;
  }
  lv_init();
  soy_pinch_draw_init();
  lv_tick_set_cb(ticks);
  display = lv_display_create(W, H);
  lv_display_set_color_format(display, LV_COLOR_FORMAT_XRGB8888);
  lv_display_set_buffers(display, pixels, NULL, PIXEL_BYTES,
                         LV_DISPLAY_RENDER_MODE_DIRECT);
  lv_display_set_flush_cb(display, flush);
  /* Leave headroom for scheduling jitter; 16 ms timer starts drift whenever
   * drawing completes late. A still LVGL tree does not submit new frames. */
  lv_timer_set_period(lv_display_get_refr_timer(display), 8);
  lv_display_add_event_cb(display, refresh_event, LV_EVENT_REFR_START, NULL);
  flat(lv_screen_active());
  lv_obj_set_scrollable(lv_screen_active(), false);
  pointer = lv_indev_create();
  lv_indev_set_type(pointer, LV_INDEV_TYPE_POINTER);
  lv_indev_set_read_cb(pointer, read_pointer);
  lv_indev_set_scroll_limit(pointer, 14);
  lv_indev_set_scroll_throw(pointer, 12);
  lv_indev_set_long_press_time(pointer, 600);
  lv_indev_set_pinch_up_threshold(pointer, 1.05f);
  lv_indev_set_pinch_down_threshold(pointer, .95f);
  /* This UI has no rotate action. Small incidental rotation must not win
   * arbitration before a pinch crosses its scale threshold. */
  lv_indev_set_rotation_rad_threshold(pointer, .6f);
  lv_timer_set_period(lv_indev_get_read_timer(pointer), 8);
  stats();
  for (int i = 0; i < NS; i++)
    views[i].zoom = 1;
  build_pages();
  lv_refr_now(display);
  if (render)
    return capture(output) ? 2 : 0;
  lv_display_trigger_activity(display);
  path(p, sizeof p, rundir, "control");
  struct stat st;
  if (lstat(p, &st)) {
    if (mkfifo(p, 0600))
      return 2;
  } else if (!S_ISFIFO(st.st_mode) || st.st_uid != geteuid())
    return 2;
  ctl = open(p, O_RDWR | O_NONBLOCK | O_CLOEXEC);
  if (ctl < 0)
    return 2;
  path(p, sizeof p, rundir, "journal.jsonl");
  journal = fopen(p, "ae");
  mark_blanked(0); /* a renderer that crashed while blanked left the flag */
  note("\"e\":\"start\",\"scene\":\"%s\",\"scenes\":%d", scenes[current].id,
       count);
  snprintf(noted_scene, sizeof noted_scene, "%s", scenes[current].id);
  signal(SIGINT, signal_handler);
  signal(SIGTERM, signal_handler);
  signal(SIGHUP, signal_handler);
  set_backlight(1);
  open_keys();
  /* Real-time priority below the touch driver (n90-touch, FIFO 20) so
   * tailscaled bursts and telemetry readers cannot preempt a frame. The
   * loop sleeps in poll() when nothing moves, and the kernel's RT throttling
   * keeps 5% of each second for SSH. SOY_RT=0 opts out. */
  if (direct_display && (!getenv("SOY_RT") || strcmp(getenv("SOY_RT"), "0"))) {
    struct sched_param rt = {.sched_priority = 10};
    if (sched_setscheduler(0, SCHED_FIFO, &rt))
      perror("SCHED_FIFO");
  }
  double nextstats = now() + .2, nextstatus = 0, prepare_after = now() + .15;
  unsigned stat_phase = 0;
  char commands[4096];
  size_t len = 0;
  while (!stopping) {
    double t = now();
    int moving = contacts_active || lv_obj_is_scrolling(pager) ||
                 lv_obj_is_scrolling(views[current].body) ||
                 (sheet && lv_obj_is_scrolling(sheet));
    if (moving && !blank_screen) {
      prepare_after = t + .15;
      lv_display_trigger_activity(display);
    }
    /* Each source still samples once per second during gestures. Spread the
     * independent reads across frames instead of blocking one frame on all
     * telemetry and device discovery at once. */
    if (t >= nextstats) {
      double began = now();
      switch (stat_phase) {
      case 0:
        stats_battery();
        break;
      case 1:
        stats_memory();
        break;
      case 2:
        stats_storage();
        break;
      case 3:
        stats_network();
        break;
      case 4:
        soy_input_scan();
        open_keys();
        break;
      }
      nextstats += .2;
      if (nextstats < t)
        nextstats = t + .2;
      /* Updating a live scene while fingers or animations are active would
       * discard motion. Rebuild telemetry only when that page is resting. */
      if (!blank_screen && stat_phase == 3 && strstr(scenes[current].body, "{{") &&
          !contacts_active && !sheet && !lv_obj_is_scrolling(pager) &&
          !lv_obj_is_scrolling(views[current].body)) {
        int scroll = lv_obj_get_scroll_y(views[current].body);
        build_body(current);
        lv_obj_scroll_to_y(views[current].body, scroll, LV_ANIM_OFF);
      }
      if (stat_phase == 0 && (battery_noted < 0 || t - battery_noted >= 300)) {
        char state[48];
        note("\"e\":\"battery\",\"state\":\"%s\",\"mv\":%d,\"percent\":%d",
             quoted(battery_state, state, sizeof state), battery_mv, battery);
        battery_noted = t;
      }
      stats_end = now();
      stats_ms = (stats_end - began) * 1000;
      stat_phase = (stat_phase + 1) % 5;
    }
    if (close_pending)
      close_sheet();
    if (zoom_pending >= 0) {
      int level = zoom_pending;
      zoom_pending = -1;
      resize_text(current, level, zoom_anchor);
      end_preview(0);
    }
    if (reloading || reload_requested) {
      reloading = reload_requested = 0;
      end_preview(0);
      zoom_pending = -1;
      cancel_motion();
      if (!load_scenes()) {
        rebuild_pending = 1;
        note("\"e\":\"scenes\",\"count\":%d", count);
      }
    }
    if (rebuild_pending) {
      rebuild_pending = 0;
      build_pages();
    }
    if (!blank_screen && t >= prepare_after && !moving && !sheet && !multi_latched &&
        !pointer_pressed)
      prepare_page();
    if (!blank_screen) {
      /* Release snaps, momentum and sheet settles run on LVGL's 8 ms anim
       * timer. A frame takes ~12 ms, so waiting for the next anim tick after
       * one completes misses 16.67 ms. While anything animates, step the
       * animations and draw again at once. */
      int animating = lv_anim_count_running();
      if (animating) {
        lv_anim_refr_now();
        lv_timer_ready(lv_display_get_refr_timer(display));
      }
      lv_timer_handler();
      /* An animation's last step and its scroll-end handlers invalidate
       * content after this refresh started; draw it now, not a tick later. */
      if (animating || moving)
        lv_refr_now(display);
      if (idle_seconds && !contacts_active &&
          lv_display_get_inactive_time(display) >= idle_seconds * 1000u)
        sleep_display("idle");
    }
    if (t >= nextstatus) {
      double began = now();
      status();
      status_end = now();
      status_ms = (status_end - began) * 1000;
      /* Ten times a second for tools that watch motion; while the screen is
       * blanked nothing moves, and writing it was most of Soy's idle CPU. */
      nextstatus = t + (blank_screen ? 2 : .1);
    }
    if (positions_due && t >= positions_due && !moving && !pointer_pressed)
      save_positions();
    struct pollfd fds[10] = {{ctl, POLLIN, 0}};
    int nfds = 1 + soy_input_pollfds(fds + 1, 8);
    int keyslot = -1;
    if (keyfd >= 0) {
      keyslot = nfds;
      fds[nfds++] = (struct pollfd){keyfd, POLLIN, 0};
    }
    /* A refresh that exceeded its period is already due. Do not add a
     * mandatory extra millisecond to every late frame. Idle timers still wait.
     */
    /* Blanked, only input, the control FIFO or a signal has work for us;
     * the status file waits up to a second. */
    uint32_t wait = blank_screen ? 1000 : lv_timer_get_time_to_next();
    poll(fds, nfds, blank_screen ? 1000 : clamp(wait, 0, 8));
    if (keyslot >= 0 && fds[keyslot].revents & (POLLIN | POLLHUP | POLLERR))
      read_keys();
    for (int i = 1; i < (keyslot >= 0 ? keyslot : nfds); i++)
      if (fds[i].revents & (POLLIN | POLLHUP | POLLERR)) {
        /* Preserve LVGL's bounded input processing and timer ownership. A
         * queued contact must not wait for the next periodic input tick. */
        if (blank_screen)
          lv_indev_read(pointer);
        else {
          lv_timer_ready(lv_indev_get_read_timer(pointer));
          lv_timer_ready(lv_display_get_refr_timer(display));
        }
        break;
      }
    if (fds[0].revents & POLLIN) {
      char buf[1024];
      ssize_t n;
      while ((n = read(ctl, buf, sizeof buf)) > 0)
        for (ssize_t j = 0; j < n; j++) {
          if (buf[j] == '\n') {
            commands[len] = 0;
            command(commands);
            len = 0;
          } else if (len + 1 < sizeof commands)
            commands[len++] = buf[j];
          else
            len = 0;
        }
    }
  }
  status();
  soy_input_close();
  close(ctl);
  if (fb >= 0)
    close(fb);
  soy_display_close();
  if (ttyfd >= 0) {
    if (tty_mode >= 0)
      ioctl(ttyfd, KDSETMODE, tty_mode);
    close(ttyfd);
  }
  if (lockfd >= 0)
    close(lockfd);
  end_preview(0);
  if (blank_screen)
    lv_obj_delete(blank_screen);
  if (backlight_state == 0)
    set_backlight(1);
  if (keyfd >= 0)
    close(keyfd);
  lv_obj_clean(lv_screen_active());
  for (int i = 0; i < NS; i++) {
    free_blocks(&views[i]);
    for (int z = 0; z < 5; z++)
      free_blocks(&prepared[i][z]);
    free(scenes[i].body);
  }
  lv_deinit();
  for (int i = 0; i < 4; i++)
    free(fonts[i].data);
  for (int i = 0; i < 3; i++)
    free(extra_fonts[i].data);
  return 0;
}
