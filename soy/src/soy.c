#define _GNU_SOURCE
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <linux/fb.h>
#include <linux/input.h>
#include <linux/kd.h>
#include <math.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <time.h>
#include <unistd.h>

/* Text scenes, not a terminal emulator. No shell evaluation, HTML or network
 * API. */
#define W 640
#define H 960
#define TOP 112
#define BOTTOM 860
#define NS 32
#define MAX_MD (128 * 1024)
#define BG 0x090e0c
#define INK 0xe4ebe4
#define MUTED 0x84958b
#define LINE 0x26382d
#define SAGE 0xb6e3a4
#define CYAN 0x90d7df
#define AMBER 0xf1c27d

typedef struct {
  unsigned w, h, n;
  unsigned char *data;
} Font;
typedef struct {
  char id[48], label[64];
  uint32_t accent;
  int hero, scroll, height;
  char *body;
} Scene;
typedef struct {
  int fd, down, x, y, xmin, xmax, ymin, ymax, slot, mt, changed, desync,
      suppressed;
} Input;
static Font fonts[4];
static Scene scenes[NS];
static int count, current, headless, render_only, dirty = 1, cliptop,
                                                  clipbottom = H;
static char assetdir[512] = "assets", scenedir[512] = "scenes",
            rundir[512] = "/run/soy";
static uint32_t screen[W * H], previous[W * H], target[W * H], last[W * H];
static uint32_t *canvas = screen;
static int fb = -1, tty = -1, ctl = -1, firstframe = 1;
static unsigned char *mapping;
static struct fb_fix_screeninfo fix;
static struct fb_var_screeninfo var;
static volatile sig_atomic_t stopping, reloading;
static Input inputs[16];
static int ninputs;
static unsigned long frames, evdev_events;
static double paint_max, paint_sum, paint_last, samples[256];
static double scan_ms, transfer_ms, retain_ms;
static const char *last_input = "none";
static double anim_start;
static int anim_dir, anim_from, anim_to = W;
static int drag_index = -1, drag_shift;
static int pointer_down, px0, py0, pxlast, pylast, axis;
static double pointer_start;
static int battery = -1;
static char battery_state[96] = "Battery unavailable";
static double battery_history[60], network_history[60];
static int bn, nn;
static double battery_tick = -1;
static unsigned long long rx_old, tx_old;
static double rx_rate, tx_rate, stat_time;
static char net_name[32] = "No link", wifi_state[64] = "Not connected";
static long mem_total, mem_available;
static unsigned long long disk_total, disk_available;
static int ram_root;

static double now(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec + t.tv_nsec / 1e9;
}
static void on_signal(int sig) {
  if (sig == SIGHUP)
    reloading = 1;
  else
    stopping = 1;
}
static int clamp(int v, int low, int high) {
  return v < low ? low : v > high ? high : v;
}
static int valid_id(const char *s) {
  if (!*s || strlen(s) > 40)
    return 0;
  for (; *s; s++)
    if (!isalnum((unsigned char)*s) && *s != '-' && *s != '_')
      return 0;
  return 1;
}
static void path(char *out, size_t n, const char *dir, const char *file) {
  if (snprintf(out, n, "%s/%s", dir, file) >= (int)n) {
    fprintf(stderr, "Path too long\n");
    exit(2);
  }
}
static uint32_t read32(const void *p) {
  const unsigned char *b = p;
  return b[0] | b[1] << 8 | b[2] << 16 | (uint32_t)b[3] << 24;
}
static int read_text(const char *p, char *s, size_t n) {
  FILE *f = fopen(p, "r");
  if (!f)
    return -1;
  size_t z = fread(s, 1, n - 1, f);
  s[z] = 0;
  fclose(f);
  while (z && isspace((unsigned char)s[z - 1]))
    s[--z] = 0;
  return 0;
}
static void rect(int x, int y, int w, int h, uint32_t c) {
  int x1 = clamp(x, 0, W), x2 = clamp(x + w, 0, W),
      y1 = clamp(y, cliptop, clipbottom),
      y2 = clamp(y + h, cliptop, clipbottom);
  for (int j = y1; j < y2; j++)
    for (int i = x1; i < x2; i++)
      canvas[j * W + i] = c;
}
static void line(int x0, int y0, int x1, int y1, uint32_t c) {
  int dx = abs(x1 - x0), sx = x0 < x1 ? 1 : -1, dy = -abs(y1 - y0),
      sy = y0 < y1 ? 1 : -1, e = dx + dy;
  for (;;) {
    rect(x0, y0, 2, 2, c);
    if (x0 == x1 && y0 == y1)
      break;
    int e2 = e * 2;
    if (e2 >= dy) {
      e += dy;
      x0 += sx;
    }
    if (e2 <= dx) {
      e += dx;
      y0 += sy;
    }
  }
}
static int load_font(Font *f, int size) {
  char p[600], name[64];
  snprintf(name, sizeof name, "mono-%d.soyfont", size);
  path(p, sizeof p, assetdir, name);
  FILE *fp = fopen(p, "rb");
  if (!fp)
    return -1;
  unsigned char hd[16];
  if (fread(hd, 1, 16, fp) != 16 || read32(hd) != 0x31594f53) {
    fclose(fp);
    return -1;
  }
  f->w = read32(hd + 4);
  f->h = read32(hd + 8);
  f->n = read32(hd + 12);
  if (!f->w || f->w > 128 || !f->h || f->h > 160 || !f->n || f->n > 2048) {
    fclose(fp);
    return -1;
  }
  size_t bytes = (4 + f->w * f->h) * f->n;
  f->data = malloc(bytes);
  int ok = f->data && fread(f->data, 1, bytes, fp) == bytes;
  fclose(fp);
  return ok ? 0 : -1;
}
static const unsigned char *glyph(Font *f, uint32_t c) {
  unsigned lo = 0, hi = f->n, step = 4 + f->w * f->h;
  while (lo < hi) {
    unsigned mid = (lo + hi) / 2;
    uint32_t key = read32(f->data + mid * step);
    if (key < c)
      lo = mid + 1;
    else
      hi = mid;
  }
  if (lo < f->n && read32(f->data + lo * step) == c)
    return f->data + lo * step + 4;
  if (c != '?')
    return glyph(f, '?');
  return NULL;
}
static void letter(Font *f, uint32_t cp, int x, int y, uint32_t color) {
  if (x + (int)f->w <= 0 || x >= W || y + (int)f->h <= cliptop ||
      y >= clipbottom)
    return;
  const unsigned char *g = glyph(f, cp);
  if (!g)
    return;
  unsigned cr = color >> 16, cg = (color >> 8) & 255, cb = color & 255;
  for (unsigned j = 0; j < f->h; j++) {
    int yy = y + j;
    if (yy < cliptop || yy >= clipbottom)
      continue;
    for (unsigned i = 0; i < f->w; i++) {
      int xx = x + i;
      if (xx < 0 || xx >= W)
        continue;
      unsigned a = g[j * f->w + i];
      if (!a)
        continue;
      uint32_t d = canvas[yy * W + xx];
      unsigned r = ((d >> 16) * (255 - a) + cr * a + 127) / 255,
               b = ((d & 255) * (255 - a) + cb * a + 127) / 255,
               gr = (((d >> 8) & 255) * (255 - a) + cg * a + 127) / 255;
      canvas[yy * W + xx] = (r << 16) | (gr << 8) | b;
    }
  }
}
static uint32_t utf8(const char **p) {
  const unsigned char *s = (const unsigned char *)*p;
  uint32_t c = *s++;
  int n = 0;
  if (c < 128) {
    *p = (const char *)s;
    return c;
  }
  if ((c & 0xe0) == 0xc0) {
    c &= 31;
    n = 1;
  } else if ((c & 0xf0) == 0xe0) {
    c &= 15;
    n = 2;
  } else if ((c & 0xf8) == 0xf0) {
    c &= 7;
    n = 3;
  } else {
    (*p)++;
    return '?';
  }
  for (int i = 0; i < n; i++) {
    if ((*s & 0xc0) != 0x80) {
      (*p)++;
      return '?';
    }
    c = (c << 6) | (*s++ & 63);
  }
  *p = (const char *)s;
  return c;
}
static void text(int x, int y, const char *s, int font, uint32_t color) {
  Font *f = &fonts[font];
  while (*s) {
    letter(f, utf8(&s), x, y, color);
    x += f->w;
  }
}
static void pretty_bytes(double v, char *out, size_t n, const char *suffix) {
  const char *u[] = {"B", "KiB", "MiB", "GiB"};
  int i = 0;
  while (v >= 1024 && i < 3) {
    v /= 1024;
    i++;
  }
  snprintf(out, n, v < 10 && i ? "%.1f %s%s" : "%.0f %s%s", v, u[i], suffix);
}
static void history(double *a, int *n, double value) {
  if (*n < 60)
    a[(*n)++] = value;
  else {
    memmove(a, a + 1, 59 * sizeof(double));
    a[59] = value;
  }
}
static void stats(void) {
  double t = now(), elapsed = stat_time ? t - stat_time : 0;
  FILE *f;
  char buf[512];
  battery = -1;
  strcpy(battery_state, "Battery unavailable");
  glob_t g = {0};
  if (!glob("/sys/class/power_supply/*/capacity", 0, NULL, &g)) {
    for (size_t i = 0; i < g.gl_pathc; i++)
      if (!read_text(g.gl_pathv[i], buf, sizeof buf)) {
        int v = atoi(buf);
        if (v >= 0 && v <= 100) {
          battery = v;
          char p[600];
          snprintf(p, sizeof p, "%s", g.gl_pathv[i]);
          char *q = strrchr(p, '/');
          strcpy(q, "/status");
          if (read_text(p, battery_state, sizeof battery_state))
            strcpy(battery_state, "Battery");
          break;
        }
      }
  }
  globfree(&g);
  if (battery >= 0 && (battery_tick < 0 || t - battery_tick >= 60)) {
    history(battery_history, &bn, battery);
    battery_tick = t;
  }
  f = fopen("/proc/meminfo", "r");
  if (f) {
    while (fgets(buf, sizeof buf, f)) {
      long v;
      if (sscanf(buf, "MemTotal: %ld", &v) == 1)
        mem_total = v;
      if (sscanf(buf, "MemAvailable: %ld", &v) == 1)
        mem_available = v;
    }
    fclose(f);
  }
  f = fopen("/proc/mounts", "r");
  ram_root = 0;
  if (f) {
    while (fgets(buf, sizeof buf, f)) {
      char mount[128], type[32];
      if (sscanf(buf, "%*s %127s %31s", mount, type) == 2 &&
          !strcmp(mount, "/"))
        ram_root = !strcmp(type, "rootfs") || !strcmp(type, "tmpfs") ||
                   !strcmp(type, "ramfs");
    }
    fclose(f);
  }
  struct statvfs fs;
  if (!statvfs("/", &fs)) {
    disk_total = (unsigned long long)fs.f_blocks * fs.f_frsize;
    disk_available = (unsigned long long)fs.f_bavail * fs.f_frsize;
  }
  char chosen[32] = "", wifi[32] = "";
  unsigned long long rx = 0, tx = 0;
  glob_t wg = {0};
  if (!glob("/sys/class/net/*/wireless", 0, NULL, &wg) && wg.gl_pathc) {
    const char *p = wg.gl_pathv[0] + strlen("/sys/class/net/");
    size_t n = strcspn(p, "/");
    if (n < sizeof wifi) {
      memcpy(wifi, p, n);
      wifi[n] = 0;
    }
  }
  globfree(&wg);
  f = fopen("/proc/net/route", "r");
  if (f) {
    while (fgets(buf, sizeof buf, f)) {
      char dev[32];
      unsigned long dest;
      unsigned flags;
      if (sscanf(buf, "%31s %lx %*s %x", dev, &dest, &flags) == 3 &&
          dest == 0 && (flags & 1)) {
        strcpy(chosen, dev);
        break;
      }
    }
    fclose(f);
  }
  if (!*chosen) {
    strcpy(chosen, "usb0");
  }
  snprintf(net_name, sizeof net_name, "%s", chosen);
  strcpy(wifi_state, *wifi ? "Not connected" : "Unavailable");
  if (*wifi) {
    char p[160];
    snprintf(p, sizeof p, "/sys/class/net/%s/operstate", wifi);
    if (!read_text(p, buf, sizeof buf) && !strcmp(buf, "up"))
      strcpy(wifi_state, "Connected");
  }
  char p[160];
  snprintf(p, sizeof p, "/sys/class/net/%s/statistics/rx_bytes", chosen);
  if (!read_text(p, buf, sizeof buf))
    rx = strtoull(buf, NULL, 10);
  snprintf(p, sizeof p, "/sys/class/net/%s/statistics/tx_bytes", chosen);
  if (!read_text(p, buf, sizeof buf))
    tx = strtoull(buf, NULL, 10);
  rx_rate = elapsed > 0 && rx >= rx_old ? (rx - rx_old) / elapsed : 0;
  tx_rate = elapsed > 0 && tx >= tx_old ? (tx - tx_old) / elapsed : 0;
  rx_old = rx;
  tx_old = tx;
  stat_time = t;
  history(network_history, &nn, rx_rate + tx_rate);
}
static const char *binding(const char *key, char *out, size_t n) {
  if (!strcmp(key, "battery.percent")) {
    if (battery >= 0)
      snprintf(out, n, "%d%%", battery);
    else
      snprintf(out, n, "—");
  } else if (!strcmp(key, "battery.state"))
    snprintf(out, n, "%s", battery_state);
  else if (!strcmp(key, "net.wifi"))
    snprintf(out, n, "%s", wifi_state);
  else if (!strcmp(key, "net.link"))
    snprintf(out, n, "%s", !strcmp(net_name, "usb0") ? "USB" : net_name);
  else if (!strcmp(key, "net.rx"))
    pretty_bytes(rx_rate, out, n, "/s");
  else if (!strcmp(key, "net.tx"))
    pretty_bytes(tx_rate, out, n, "/s");
  else if (!strcmp(key, "memory.used"))
    pretty_bytes((mem_total - mem_available) * 1024., out, n, "");
  else if (!strcmp(key, "memory.available"))
    pretty_bytes(mem_available * 1024., out, n, "");
  else if (!strcmp(key, "storage.kind"))
    snprintf(out, n, "%s", ram_root ? "RAM filesystem" : "Root filesystem");
  else if (!strcmp(key, "storage.usage")) {
    if (!disk_total)
      snprintf(out, n, "Phone flash is not mounted.");
    else {
      char a[40], b[40];
      pretty_bytes(disk_total - disk_available, a, sizeof a, "");
      pretty_bytes(disk_total, b, sizeof b, "");
      snprintf(out, n, "%s / %s", a, b);
    }
  } else {
    snprintf(out, n, "[unavailable]");
  }
  return out;
}
static void expand(const char *src, char *out, size_t cap) {
  size_t n = 0;
  while (*src && n + 1 < cap) {
    if (src[0] == '{' && src[1] == '{') {
      const char *end = strstr(src + 2, "}}");
      if (end && end - src < 100) {
        char key[100], v[128];
        memcpy(key, src + 2, end - src - 2);
        key[end - src - 2] = 0;
        binding(key, v, sizeof v);
        size_t len = strlen(v);
        if (n + len >= cap)
          break;
        memcpy(out + n, v, len);
        n += len;
        src = end + 2;
        continue;
      }
    }
    out[n++] = *src++;
  }
  out[n] = 0;
}
static int load_scenes(void) {
  Scene *fresh = calloc(NS, sizeof(Scene));
  if (!fresh)
    return -1;
  int num = 0;
  char p[600], row[128], error[128] = "Invalid scene bundle";
  path(p, sizeof p, scenedir, "index");
  FILE *f = fopen(p, "r");
  if (!f) {
    free(fresh);
    return -1;
  }
  while (fgets(row, sizeof row, f)) {
    row[strcspn(row, "\r\n")] = 0;
    if (!*row || *row == '#')
      continue;
    if (num >= NS || !valid_id(row))
      goto fail;
    for (int i = 0; i < num; i++)
      if (!strcmp(fresh[i].id, row))
        goto fail;
    Scene *s = &fresh[num];
    strcpy(s->id, row);
    snprintf(s->label, sizeof s->label, "%s", s->id);
    s->accent = SAGE;
    char name[64];
    snprintf(name, sizeof name, "%s.md", s->id);
    path(p, sizeof p, scenedir, name);
    FILE *md = fopen(p, "rb");
    if (!md)
      goto fail;
    if (fseek(md, 0, SEEK_END)) {
      fclose(md);
      goto fail;
    }
    long bytes = ftell(md);
    if (bytes <= 0 || bytes > MAX_MD) {
      fclose(md);
      goto fail;
    }
    rewind(md);
    char *raw = calloc(bytes + 1, 1);
    if (!raw) {
      fclose(md);
      goto fail;
    }
    if (fread(raw, 1, bytes, md) != (size_t)bytes || memchr(raw, 0, bytes)) {
      fclose(md);
      free(raw);
      goto fail;
    }
    fclose(md);
    s->body = raw;
    if (strncmp(raw, "---\n", 4)) {
      goto fail;
    }
    char *end = strstr(raw + 4, "\n---\n");
    if (!end)
      goto fail;
    *end = 0;
    char *save;
    int id_seen = 0;
    for (char *ln = strtok_r(raw + 4, "\n", &save); ln;
         ln = strtok_r(NULL, "\n", &save)) {
      char *colon = strchr(ln, ':');
      if (!colon)
        goto fail;
      *colon++ = 0;
      while (*colon == ' ')
        colon++;
      if (!strcmp(ln, "id")) {
        if (strcmp(colon, row))
          goto fail;
        id_seen = 1;
      } else if (!strcmp(ln, "label")) {
        if (strlen(colon) >= sizeof s->label)
          goto fail;
        strcpy(s->label, colon);
      } else if (!strcmp(ln, "accent")) {
        if (!strcmp(colon, "amber"))
          s->accent = AMBER;
        else if (!strcmp(colon, "cyan"))
          s->accent = CYAN;
        else if (!strcmp(colon, "muted"))
          s->accent = MUTED;
        else if (strcmp(colon, "sage"))
          goto fail;
      } else if (!strcmp(ln, "hero"))
        s->hero = !strcmp(colon, "true");
      else if (strcmp(ln, "source"))
        goto fail;
    }
    if (!id_seen) {
      goto fail;
    }
    char *body = strdup(end + 5);
    free(raw);
    s->body = body;
    if (!body)
      goto fail;
    /* Reject terminal controls. Markdown is inert text. */
    for (const unsigned char *c = (unsigned char *)body; *c; c++)
      if (*c < 32 && *c != '\n' && *c != '\t' && *c != '\r')
        goto fail;
    num++;
  }
  fclose(f);
  f = NULL;
  if (num <= 0 || num > NS)
    goto fail;
  char selected[48] = "";
  if (count)
    strcpy(selected, scenes[current].id);
  for (int i = 0; i < num; i++)
    for (int j = 0; j < count; j++)
      if (!strcmp(fresh[i].id, scenes[j].id))
        fresh[i].scroll = scenes[j].scroll;
  for (int i = 0; i < count; i++) {
    free(scenes[i].body);
  }
  memcpy(scenes, fresh, num * sizeof(Scene));
  count = num;
  current = 0;
  for (int i = 0; i < count; i++)
    if (!strcmp(selected, scenes[i].id))
      current = i;
  free(fresh);
  dirty = 1;
  return 0;
fail:
  if (f)
    fclose(f);
  for (int i = 0; i < NS; i++)
    free(fresh[i].body);
  free(fresh);
  fprintf(stderr, "%s\n", error);
  return -1;
}
/* Inline Markdown styling is parsed into glyphs, then wrapped at word
 * boundaries. */
typedef struct {
  uint32_t cp, color;
  int bold;
} Cell;
static int paragraph(const char *s, int x, int y, int width, int font,
                     uint32_t color, uint32_t accent, int code) {
  Cell *cells = calloc(strlen(s) + 1, sizeof(Cell));
  if (!cells)
    return y;
  int n = 0, bold = 0, em = 0, link_mode = 0, inline_code = code;
  while (*s) {
    if (!code && s[0] == '*' && s[1] == '*') {
      bold = !bold;
      s += 2;
      continue;
    }
    if (!code && *s == '*') {
      em = !em;
      s++;
      continue;
    }
    if (!code && *s == '`') {
      inline_code = !inline_code;
      s++;
      continue;
    }
    if (!code && *s == '[') {
      link_mode = 1;
      s++;
      continue;
    }
    if (!code && *s == ']' && s[1] == '(') {
      const char *e = strchr(s + 2, ')');
      if (e) {
        s = e + 1;
        link_mode = 0;
        continue;
      }
    }
    if (*s == '\\' && s[1])
      s++;
    uint32_t cp = utf8(&s);
    cells[n++] = (Cell){cp,
                        link_mode || inline_code ? accent
                        : em                     ? MUTED
                        : bold                   ? INK
                                                 : color,
                        bold};
  }
  int cols = width / (int)fonts[font].w;
  if (cols < 1)
    cols = 1;
  int start = 0, lh = fonts[font].h + 3;
  while (start < n) {
    int end = start + cols;
    if (end > n)
      end = n;
    if (end < n) {
      int space = end;
      while (space > start && cells[space].cp != ' ')
        space--;
      if (space > start)
        end = space;
    }
    int xx = x;
    for (int i = start; i < end; i++) {
      letter(&fonts[font], cells[i].cp, xx, y, cells[i].color);
      if (cells[i].bold)
        letter(&fonts[font], cells[i].cp, xx + 1, y, cells[i].color);
      xx += fonts[font].w;
    }
    y += lh;
    start = end;
    while (start < n && cells[start].cp == ' ')
      start++;
  }
  free(cells);
  return y;
}
static int graph(int y, int battery_graph, uint32_t accent) {
  double *a = battery_graph ? battery_history : network_history;
  int n = battery_graph ? bn : nn;
  int left = 34, base = y + 164;
  if (!n) {
    text(left, y + 30, "No history yet", 1, MUTED);
    return y + 116;
  } else {
    double max = battery_graph ? 100 : 1;
    for (int i = 0; i < n; i++)
      if (a[i] > max)
        max = a[i];
    char scale[64];
    if (battery_graph)
      snprintf(scale, sizeof scale, "100%%");
    else
      pretty_bytes(max, scale, sizeof scale, "/s total");
    text(left, y + 16, scale, 0, MUTED);
    rect(left, base, 572, 1, LINE);
    rect(left, base - 96, 572, 1, LINE);
    int oldx = left + 16 + (int)((60 - n) * 540.0 / 59),
        oldy = base - (int)(a[0] / max * 96);
    for (int i = 0; i < n; i++) {
      int x = left + 16 + (int)((60 - n + i) * 540.0 / 59),
          yy = base - (int)(a[i] / max * 96);
      if (i)
        line(oldx, oldy, x, yy, accent);
      rect(x - 2, yy - 2, 5, 5, accent);
      oldx = x;
      oldy = yy;
    }
  }
  text(left, y + 188, battery_graph ? "−60 min" : "−60 s", 0, MUTED);
  text(562, y + 188, "now", 0, MUTED);
  return y + 244;
}
static void compose(void) {
  Scene *s = &scenes[current];
  canvas = target;
  cliptop = 0;
  clipbottom = H;
  rect(0, 0, W, H, BG);
  text(34, 30, s->label, 1, MUTED);
  cliptop = TOP;
  clipbottom = BOTTOM;
  int y = TOP - s->scroll, code = 0, first = 1;
  const char *cursor = s->body;
  while (*cursor) {
    const char *e = strchr(cursor, '\n');
    size_t len = e ? (size_t)(e - cursor) : strlen(cursor);
    char *raw = malloc(len + 1), *expanded = malloc(len + 2048);
    if (!raw || !expanded) {
      free(raw);
      free(expanded);
      break;
    }
    memcpy(raw, cursor, len);
    raw[len] = 0;
    if (!strncmp(raw, "```", 3)) {
      code = !code;
      y += 12;
    } else if (!*raw)
      y += 20;
    else if (!strcmp(raw, "{{graph.battery}}"))
      y = graph(y, 1, s->accent);
    else if (!strcmp(raw, "{{graph.network}}"))
      y = graph(y, 0, s->accent);
    else {
      expand(raw, expanded, len + 2048);
      char *txt = expanded;
      int font = 1, indent = 0;
      uint32_t color = INK;
      if (!code && txt[0] == '#') {
        int level = 0;
        while (*txt == '#') {
          level++;
          txt++;
        }
        if (*txt == ' ')
          txt++;
        font = level == 1 ? (s->hero && first ? 3 : 2) : 1;
        color = s->hero && level == 1 ? s->accent : INK;
        y += first ? 0 : 12;
        first = 0;
      } else if (!code && txt[0] == '>' && (txt[1] == ' ' || !txt[1])) {
        txt++;
        if (*txt == ' ')
          txt++;
        indent = 22;
        color = MUTED;
        rect(34, y, 3, fonts[1].h, s->accent);
      } else if (!code && ((txt[0] == '-' || txt[0] == '*') && txt[1] == ' ')) {
        text(34, y, "·", 1, s->accent);
        txt += 2;
        indent = 24;
      }
      if (code) {
        rect(26, y, 588, fonts[1].h + 4, 0x101a14);
        color = s->accent;
      }
      y = paragraph(txt, 34 + indent, y, 572 - indent, font, color, s->accent,
                    code);
    }
    free(raw);
    free(expanded);
    cursor = e ? e + 1 : cursor + len;
  }
  s->height = y + s->scroll - TOP;
  if (s->height < 0)
    s->height = 0;
  int maxscroll = s->height - (BOTTOM - TOP) + 24;
  if (maxscroll < 0)
    maxscroll = 0;
  if (s->scroll > maxscroll) {
    s->scroll = maxscroll;
    dirty = 1;
  }
  if (maxscroll) {
    int thumb = (BOTTOM - TOP) * (BOTTOM - TOP) / (s->height + 24);
    if (thumb < 28)
      thumb = 28;
    int pos = TOP + (BOTTOM - TOP - thumb) * (double)s->scroll / maxscroll;
    rect(626, TOP, 3, BOTTOM - TOP, LINE);
    rect(626, pos, 3, thumb, s->accent);
  }
  cliptop = 0;
  clipbottom = H;
  /* A familiar, quiet page control. Large hit region, small visual marks. */
  int visible = count < 9 ? count : 9;
  int firstdot = clamp(current - visible / 2, 0, count - visible);
  int start = W / 2 - (visible - 1) * 32 / 2;
  for (int j = 0; j < visible; j++) {
    int selected = firstdot + j == current;
    rect(start + j * 32 - (selected ? 7 : 3), 916, selected ? 14 : 6, 6,
         selected ? INK : MUTED);
  }
  canvas = screen;
}
static uint32_t fb_pixel(uint32_t c) {
  uint32_t p = (((c >> 16) & 255) << var.red.offset) |
               (((c >> 8) & 255) << var.green.offset) |
               ((c & 255) << var.blue.offset);
  if (var.transp.length)
    p |= ((1u << var.transp.length) - 1) << var.transp.offset;
  return p;
}
static void present(void) {
  double t = now();
  scan_ms = transfer_ms = retain_ms = 0;
  if (!headless && mapping && var.red.offset == 16 && var.green.offset == 8 &&
      var.blue.offset == 0 && !var.transp.length && !var.xoffset &&
      !var.yoffset && fix.line_length == W * 4) {
    /* On this ARM libc, scanning unchanged rows costs more than submitting
     * the frame. Render only on change, then submit contiguous pixels. */
    double transfer_start = now();
    size_t done = 0, bytes = sizeof screen;
    while (done < bytes) {
      ssize_t n =
          pwrite(fb, (unsigned char *)screen + done, bytes - done, done);
      if (n < 0 && errno == EINTR)
        continue;
      if (n <= 0) {
        fprintf(stderr, "Framebuffer write failed\n");
        stopping = 1;
        break;
      }
      done += n;
    }
    transfer_ms = (now() - transfer_start) * 1000;
  } else if (!headless && mapping) {
    for (int y = 0; y < H; y++) {
      int first = 0, end = W;
      if (!firstframe) {
        while (first < W && screen[y * W + first] == last[y * W + first])
          first++;
        while (end > first && screen[y * W + end - 1] == last[y * W + end - 1])
          end--;
      }
      uint32_t *row =
          (uint32_t *)(mapping + (y + var.yoffset) * fix.line_length) +
          var.xoffset;
      if (var.red.offset == 16 && var.green.offset == 8 &&
          var.blue.offset == 0 && !var.transp.length) {
        /* The N90 boot framebuffer already matches the canvas. Burst copies
         * avoid slow per-pixel stores into the framebuffer mapping. */
        memcpy(row + first, screen + y * W + first, (end - first) * 4);
      } else {
        for (int x = first; x < end; x++)
          row[x] = fb_pixel(screen[y * W + x]);
      }
    }
  }
  if (!headless &&
      !(var.red.offset == 16 && var.green.offset == 8 && var.blue.offset == 0 &&
        !var.transp.length && !var.xoffset && !var.yoffset &&
        fix.line_length == W * 4)) {
    double retain_start = now();
    memcpy(last, screen, sizeof last);
    retain_ms = (now() - retain_start) * 1000;
  }
  firstframe = 0;
  paint_last = (now() - t) * 1000;
  paint_sum += paint_last;
  if (paint_last > paint_max)
    paint_max = paint_last;
  samples[frames % 256] = paint_last;
  frames++;
}
static int capture(const char *file) {
  FILE *f = fopen(file, "wb");
  if (!f)
    return -1;
  fprintf(f, "P6\n%d %d\n255\n", W, H);
  unsigned char row[W * 3];
  for (int y = 0; y < H; y++) {
    for (int x = 0; x < W; x++) {
      uint32_t c = screen[y * W + x];
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
static int compare_double(const void *a, const void *b) {
  double x = *(const double *)a, y = *(const double *)b;
  return (x > y) - (x < y);
}
static void status(void) {
  char p[600], tmp[600];
  path(p, sizeof p, rundir, "status.json");
  path(tmp, sizeof tmp, rundir, "status.tmp");
  FILE *f = fopen(tmp, "w");
  if (!f)
    return;
  unsigned n = frames < 256 ? frames : 256;
  double sorted[256];
  memcpy(sorted, samples, n * sizeof(double));
  qsort(sorted, n, sizeof(double), compare_double);
  fprintf(f,
          "{\"scene\":\"%s\",\"index\":%d,\"count\":%d,\"scroll\":%d,\"content_"
          "height\":%d,\"backend\":\"%s\",\"input_devices\":%d,\"evdev_"
          "events\":%lu,\"last_input\":\"%s\",\"frames\":%lu,\"present_ms_"
          "avg\":%.3f,\"present_ms_p95\":%.3f,\"present_ms_max\":%.3f,\"target_"
          "hz\":60,\"scan_ms\":%.3f,\"transfer_ms\":%.3f,\"retain_ms\":%.3f,"
          "\"scanout_sync_verified\":false}\n",
          scenes[current].id, current, count, scenes[current].scroll,
          scenes[current].height, headless ? "headless" : "framebuffer",
          ninputs, evdev_events, last_input, frames,
          frames ? paint_sum / frames : 0, n ? sorted[(n - 1) * 95 / 100] : 0,
          paint_max, scan_ms, transfer_ms, retain_ms);
  fclose(f);
  rename(tmp, p);
}
static void slide(int shift) {
  shift = clamp(shift, 0, W);
  for (int y = 0; y < BOTTOM; y++) {
    uint32_t *dst = screen + y * W, *old = previous + y * W,
             *fresh = target + y * W;
    if (anim_dir > 0) {
      memcpy(dst, old + shift, (W - shift) * 4);
      memcpy(dst + W - shift, fresh, shift * 4);
    } else {
      memcpy(dst, fresh + W - shift, shift * 4);
      memcpy(dst + shift, old, (W - shift) * 4);
    }
  }
  memcpy(screen + BOTTOM * W, previous + BOTTOM * W, (H - BOTTOM) * W * 4);
}
static void settle_pointer(void) {
  pointer_down = 0;
  drag_index = -1;
  drag_shift = 0;
  anim_start = 0;
  compose();
  memcpy(screen, target, sizeof screen);
}
static void move_to(int index) {
  if (index < 0 || index >= count || index == current)
    return;
  settle_pointer();
  memcpy(previous, screen, sizeof screen);
  anim_from = 0;
  anim_to = W;
  anim_dir = index > current ? 1 : -1;
  current = index;
  compose();
  anim_start = now();
  dirty = 0;
}
static void scroll_by(int delta) {
  Scene *s = &scenes[current];
  int max = s->height - (BOTTOM - TOP) + 24;
  if (max < 0)
    max = 0;
  s->scroll = clamp(s->scroll + delta, 0, max);
  dirty = 1;
}
static void pointer(const char *kind, int x, int y) {
  x = clamp(x, 0, W - 1);
  y = clamp(y, 0, H - 1);
  if (!strcmp(kind, "down")) {
    settle_pointer();
    memcpy(previous, screen, sizeof screen);
    pointer_down = 1;
    px0 = pxlast = x;
    py0 = pylast = y;
    axis = 0;
    pointer_start = now();
    return;
  }
  if (!pointer_down)
    return;
  int dx = x - px0, dy = y - py0;
  if (!axis && (abs(dx) > 16 || abs(dy) > 16))
    axis = abs(dx) > abs(dy) ? 1 : 2;
  if (!strcmp(kind, "move")) {
    if (axis == 2 && py0 < BOTTOM)
      scroll_by(pylast - y);
    if (axis == 1 && py0 < BOTTOM) {
      int candidate = current + (dx < 0 ? 1 : -1);
      if (candidate >= 0 && candidate < count) {
        if (candidate != drag_index) {
          int origin = current;
          current = candidate;
          compose();
          current = origin;
          drag_index = candidate;
        }
        anim_dir = dx < 0 ? 1 : -1;
        drag_shift = clamp(abs(dx), 0, W);
        slide(drag_shift);
        present();
        dirty = 0;
      } else {
        memcpy(screen, previous, sizeof screen);
        present();
        drag_index = -1;
        drag_shift = 0;
      }
    }
    pxlast = x;
    pylast = y;
    return;
  }
  if (!strcmp(kind, "up")) {
    if (axis == 1 && drag_index >= 0) {
      int commit = abs(dx) > 100 && abs(dx) > abs(dy);
      anim_from = drag_shift;
      anim_to = commit ? W : 0;
      if (commit)
        current = drag_index;
      anim_start = now();
      dirty = 0;
    } else if (!axis && now() - pointer_start < 0.7 && py0 >= 872 && y >= 872 &&
               x >= 100 && x < W - 100) {
      /* The two halves are roomy previous/next targets, as on a page control;
       * individual six-pixel dots are not separate tiny buttons. */
      move_to(current + (x < W / 2 ? -1 : 1));
    }
    pointer_down = 0;
    drag_index = -1;
  }
}

static void discover_inputs(void) {
  glob_t g = {0};
  if (glob("/dev/input/event*", 0, NULL, &g))
    return;
  for (size_t i = 0; i < g.gl_pathc && ninputs < 16; i++) {
    int fd = open(g.gl_pathv[i], O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0)
      continue;
    struct input_absinfo ax, ay, slots;
    int mt = 1;
    if (ioctl(fd, EVIOCGABS(ABS_MT_SLOT), &slots) || slots.minimum != 0 ||
        ioctl(fd, EVIOCGABS(ABS_MT_POSITION_X), &ax) ||
        ioctl(fd, EVIOCGABS(ABS_MT_POSITION_Y), &ay)) {
      mt = 0;
      if (ioctl(fd, EVIOCGABS(ABS_X), &ax) ||
          ioctl(fd, EVIOCGABS(ABS_Y), &ay)) {
        close(fd);
        continue;
      }
    }
    if (ax.maximum <= ax.minimum || ay.maximum <= ay.minimum) {
      close(fd);
      continue;
    }
    inputs[ninputs++] = (Input){.fd = fd,
                                .xmin = ax.minimum,
                                .xmax = ax.maximum,
                                .ymin = ay.minimum,
                                .ymax = ay.maximum,
                                .mt = mt};
  }
  globfree(&g);
}
static void input_read(Input *i) {
  struct input_event e;
  while (read(i->fd, &e, sizeof e) == sizeof e) {
    evdev_events++;
    last_input = "evdev";
    if (e.type == EV_SYN && e.code == SYN_DROPPED) {
      pointer_down = 0;
      i->down = 0;
      i->changed = 0;
      i->desync = 1;
      continue;
    }
    if (i->desync) {
      if (e.type == EV_SYN && e.code == SYN_REPORT) {
        struct input_absinfo ax, ay;
        int keys[2] = {ABS_MT_TRACKING_ID, -1};
        if (i->mt) {
          ioctl(i->fd, EVIOCGMTSLOTS(sizeof keys), keys);
          i->down = keys[1] >= 0;
        } else {
          unsigned char bits[(KEY_MAX + 8) / 8] = {0};
          ioctl(i->fd, EVIOCGKEY(sizeof bits), bits);
          i->down = (bits[BTN_TOUCH / 8] >> (BTN_TOUCH % 8)) & 1;
        }
        if (!ioctl(i->fd, EVIOCGABS(i->mt ? ABS_MT_POSITION_X : ABS_X), &ax))
          i->x = (ax.value - i->xmin) * (W - 1) / (i->xmax - i->xmin);
        if (!ioctl(i->fd, EVIOCGABS(i->mt ? ABS_MT_POSITION_Y : ABS_Y), &ay))
          i->y = (ay.value - i->ymin) * (H - 1) / (i->ymax - i->ymin);
        i->suppressed = i->down;
        i->desync = 0;
      }
      continue;
    }
    if (e.type == EV_ABS) {
      if (e.code == ABS_MT_SLOT) {
        i->slot = e.value;
        continue;
      }
      if (i->slot)
        continue;
      if (e.code == (i->mt ? ABS_MT_POSITION_X : ABS_X))
        i->x = (e.value - i->xmin) * (W - 1) / (i->xmax - i->xmin);
      if (e.code == (i->mt ? ABS_MT_POSITION_Y : ABS_Y))
        i->y = (e.value - i->ymin) * (H - 1) / (i->ymax - i->ymin);
      if (e.code == ABS_MT_TRACKING_ID) {
        i->down = e.value >= 0;
        i->changed = 1;
      }
    }
    if (e.type == EV_KEY && e.code == BTN_TOUCH && !i->mt) {
      i->down = e.value != 0;
      i->changed = 1;
    }
    if (e.type == EV_SYN && e.code == SYN_REPORT) {
      if (i->suppressed) {
        if (!i->down)
          i->suppressed = 0;
        continue;
      }
      if (i->down) {
        pointer(pointer_down ? "move" : "down", i->x, i->y);
      } else if (pointer_down)
        pointer("up", i->x, i->y);
      i->changed = 0;
    }
  }
}
static void command(char *s) {
  s[strcspn(s, "\r\n")] = 0;
  last_input = "remote";
  if (!strcmp(s, "next"))
    move_to(current + 1);
  else if (!strcmp(s, "prev"))
    move_to(current - 1);
  else if (!strncmp(s, "goto ", 5)) {
    for (int i = 0; i < count; i++)
      if (!strcmp(s + 5, scenes[i].id))
        move_to(i);
  } else if (!strncmp(s, "scroll ", 7)) {
    char *end;
    long v = strtol(s + 7, &end, 10);
    if (end != s + 7 && !*end && v >= -H * 10 && v <= H * 10)
      scroll_by((int)v);
  } else if (!strcmp(s, "reload")) {
    if (!load_scenes()) {
      settle_pointer();
      dirty = 1;
    }
  } else if (!strcmp(s, "capture")) {
    char p[600];
    path(p, sizeof p, rundir, "frame.ppm");
    capture(p);
  } else if (!strcmp(s, "quit"))
    stopping = 1;
  else if (!strncmp(s, "touch ", 6)) {
    char k[12];
    int x, y;
    if (sscanf(s + 6, "%11s %d %d", k, &x, &y) == 3)
      pointer(k, x, y);
  }
  status();
}
static int open_display(void) {
  fb = open("/dev/fb0", O_RDWR | O_CLOEXEC);
  if (fb < 0 || ioctl(fb, FBIOGET_FSCREENINFO, &fix) ||
      ioctl(fb, FBIOGET_VSCREENINFO, &var))
    return -1;
  if (var.xres != W || var.yres != H || var.bits_per_pixel != 32 ||
      var.red.length != 8 || var.green.length != 8 || var.blue.length != 8 ||
      var.transp.length > 8 || var.red.offset + 8 > 32 ||
      var.green.offset + 8 > 32 || var.blue.offset + 8 > 32 ||
      var.transp.offset + var.transp.length > 32 ||
      fix.line_length < (var.xoffset + W) * 4 ||
      ((size_t)var.yoffset + H) * fix.line_length > fix.smem_len)
    return -1;
  mapping = mmap(NULL, fix.smem_len, PROT_READ | PROT_WRITE, MAP_SHARED, fb, 0);
  if (mapping == MAP_FAILED) {
    mapping = NULL;
    return -1;
  }
  tty = open("/dev/tty0", O_RDWR | O_CLOEXEC);
  if (tty >= 0)
    ioctl(tty, KDSETMODE, KD_GRAPHICS);
  return 0;
}
int main(int argc, char **argv) {
  const char *output = NULL, *initial = NULL;
  int check = 0;
  umask(0077);
  for (int i = 1; i < argc; i++) {
    if (!strcmp(argv[i], "--headless"))
      headless = 1;
    else if (!strcmp(argv[i], "--check")) {
      check = 1;
      headless = 1;
    } else if (!strcmp(argv[i], "--render") && i + 1 < argc) {
      output = argv[++i];
      headless = render_only = 1;
    } else if (!strcmp(argv[i], "--scene") && i + 1 < argc)
      initial = argv[++i];
    else if (!strcmp(argv[i], "--assets") && i + 1 < argc)
      snprintf(assetdir, sizeof assetdir, "%s", argv[++i]);
    else if (!strcmp(argv[i], "--scenes") && i + 1 < argc)
      snprintf(scenedir, sizeof scenedir, "%s", argv[++i]);
    else if (!strcmp(argv[i], "--run") && i + 1 < argc)
      snprintf(rundir, sizeof rundir, "%s", argv[++i]);
    else {
      fprintf(stderr, "Usage: soy [--assets DIR] [--scenes DIR] [--run DIR] "
                      "[--scene ID] [--render FILE | --headless | --check]\n");
      return 2;
    }
  }
  int sizes[] = {24, 36, 48, 96};
  for (int i = 0; i < 4; i++)
    if (load_font(&fonts[i], sizes[i])) {
      fprintf(stderr, "Font load failed\n");
      return 2;
    }
  if (load_scenes())
    return 2;
  if (initial) {
    int found = 0;
    for (int i = 0; i < count; i++)
      if (!strcmp(initial, scenes[i].id)) {
        current = i;
        found = 1;
      }
    if (!found) {
      fprintf(stderr, "Unknown scene\n");
      return 2;
    }
  }
  if (check) {
    printf("Valid bundle: %d scenes\n", count);
    return 0;
  }
  stats();
  compose();
  memcpy(screen, target, sizeof screen);
  if (render_only)
    return capture(output) ? 2 : 0;
  if (!headless && open_display()) {
    perror("Framebuffer unavailable or unsupported");
    return 2;
  }
  if (mkdir(rundir, 0700) && errno != EEXIST) {
    perror("Runtime directory");
    return 2;
  }
  char p[600];
  path(p, sizeof p, rundir, "renderer.lock");
  int lockfd = open(p, O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0600);
  if (lockfd < 0 || flock(lockfd, LOCK_EX | LOCK_NB)) {
    fprintf(stderr, "Renderer already running or lock unavailable\n");
    return 2;
  }
  path(p, sizeof p, rundir, "control");
  struct stat st;
  if (lstat(p, &st)) {
    if (mkfifo(p, 0600)) {
      perror("Control FIFO");
      return 2;
    }
  } else if (!S_ISFIFO(st.st_mode) || st.st_uid != geteuid()) {
    fprintf(stderr, "Unsafe control FIFO\n");
    return 2;
  }
  ctl = open(p, O_RDWR | O_NONBLOCK | O_CLOEXEC);
  if (ctl < 0) {
    perror("Control FIFO");
    return 2;
  }
  signal(SIGTERM, on_signal);
  signal(SIGINT, on_signal);
  signal(SIGHUP, on_signal);
  if (!headless)
    discover_inputs();
  present();
  status();
  dirty = 0;
  double nextstats = now() + 1, nextframe = now();
  char commands[4096];
  size_t command_len = 0;
  while (!stopping) {
    if (reloading) {
      reloading = 0;
      if (!load_scenes())
        settle_pointer();
    }
    double t = now();
    if (t >= nextstats) {
      stats();
      nextstats = t + 1;
      if (strstr(scenes[current].body, "{{"))
        dirty = 1;
      status();
    }
    if (dirty && !anim_start && !(pointer_down && axis == 1)) {
      dirty = 0;
      compose();
      memcpy(screen, target, sizeof screen);
      present();
      status();
    }
    if (anim_start && t >= nextframe) {
      double progress = (t - anim_start) / .18;
      if (progress >= 1) {
        compose();
        memcpy(screen, target, sizeof screen);
        anim_start = 0;
      } else {
        double eased = 1 - pow(1 - progress, 3);
        slide(anim_from + (int)((anim_to - anim_from) * eased));
      }
      present();
      nextframe = t + 1. / 60;
      if (!anim_start)
        status();
    }
    struct pollfd pf[17];
    pf[0] = (struct pollfd){ctl, POLLIN, 0};
    for (int i = 0; i < ninputs; i++)
      pf[i + 1] = (struct pollfd){inputs[i].fd, POLLIN, 0};
    int timeout = (int)(((anim_start ? nextframe : nextstats) - now()) * 1000);
    timeout = clamp(timeout, 1, 1000);
    int ready = poll(pf, ninputs + 1, timeout);
    if (ready < 0 && errno != EINTR)
      break;
    if (pf[0].revents & POLLIN) {
      char chunk[1024];
      ssize_t n;
      while ((n = read(ctl, chunk, sizeof chunk)) > 0) {
        for (ssize_t j = 0; j < n; j++) {
          char c = chunk[j];
          if (c == '\n') {
            commands[command_len] = 0;
            command(commands);
            command_len = 0;
          } else if (command_len + 1 < sizeof commands)
            commands[command_len++] = c;
          else
            command_len = 0;
        }
      }
    }
    for (int i = 0; i < ninputs; i++)
      if (pf[i + 1].revents & POLLIN)
        input_read(&inputs[i]);
  }
  status();
  if (tty >= 0) {
    ioctl(tty, KDSETMODE, KD_TEXT);
    close(tty);
  }
  if (mapping)
    munmap(mapping, fix.smem_len);
  if (fb >= 0)
    close(fb);
  close(ctl);
  for (int i = 0; i < ninputs; i++)
    close(inputs[i].fd);
  for (int i = 0; i < count; i++)
    free(scenes[i].body);
  for (int i = 0; i < 4; i++)
    free(fonts[i].data);
  return 0;
}
