/* Shared scene data and assets. No display or gesture policy. */
#ifndef SOY_SCENE_DATA_H
#define SOY_SCENE_DATA_H
#include <ctype.h>
#include <glob.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/statvfs.h>
#include <time.h>
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
  int hero, scroll, height, zoom;
  char *body;
} Scene;
static int count, current, dirty = 1;
static char assetdir[512] = "assets", scenedir[512] = "scenes";
static Font fonts[4];
static Scene scenes[NS];
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

static inline double now(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec + t.tv_nsec / 1e9;
}
static inline int clamp(int v, int low, int high) {
  return v < low ? low : v > high ? high : v;
}
static inline int valid_id(const char *s) {
  if (!*s || strlen(s) > 40)
    return 0;
  for (; *s; s++)
    if (!isalnum((unsigned char)*s) && *s != '-' && *s != '_')
      return 0;
  return 1;
}
static inline void path(char *out, size_t n, const char *dir,
                        const char *file) {
  if (snprintf(out, n, "%s/%s", dir, file) >= (int)n) {
    fprintf(stderr, "Path too long\n");
    exit(2);
  }
}
static inline uint32_t read32(const void *p) {
  const unsigned char *b = p;
  return b[0] | b[1] << 8 | b[2] << 16 | (uint32_t)b[3] << 24;
}
static inline int read_text(const char *p, char *s, size_t n) {
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
static inline int load_font(Font *f, int size) {
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
static inline const unsigned char *glyph(Font *f, uint32_t c) {
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
static inline uint32_t utf8(const char **p) {
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
static inline void pretty_bytes(double v, char *out, size_t n,
                                const char *suffix) {
  const char *u[] = {"B", "KiB", "MiB", "GiB"};
  int i = 0;
  while (v >= 1024 && i < 3) {
    v /= 1024;
    i++;
  }
  snprintf(out, n, v < 10 && i ? "%.1f %s%s" : "%.0f %s%s", v, u[i], suffix);
}
static inline void history(double *a, int *n, double value) {
  if (*n < 60)
    a[(*n)++] = value;
  else {
    memmove(a, a + 1, 59 * sizeof(double));
    a[59] = value;
  }
}
static inline void stats_battery(void) {
  double t = now();
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
}
static inline void stats_memory(void) {
  char buf[512];
  FILE *f = fopen("/proc/meminfo", "r");
  if (f) {
    while (fgets(buf, sizeof buf, f)) {
      if (!strncmp(buf, "MemTotal:", 9))
        mem_total = strtol(buf + 9, NULL, 10);
      if (!strncmp(buf, "MemAvailable:", 13))
        mem_available = strtol(buf + 13, NULL, 10);
    }
    fclose(f);
  }
}
static inline void stats_storage(void) {
  char buf[512];
  FILE *f = fopen("/proc/mounts", "r");
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
}
static inline void stats_network(void) {
  double t = now(), elapsed = stat_time ? t - stat_time : 0;
  char buf[512];
  FILE *f;
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
static inline void stats(void) {
  stats_battery();
  stats_memory();
  stats_storage();
  stats_network();
}
static inline const char *binding(const char *key, char *out, size_t n) {
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
static inline void expand(const char *src, char *out, size_t cap) {
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
static inline int load_scenes(void) {
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
    s->zoom = 1;
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
    int lines = 1;
    for (const char *c = body; *c; c++)
      if (*c == '\n')
        lines++;
    if (lines > 2048) {
      strcpy(error, "Scene exceeds 2048 lines");
      goto fail;
    }
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
      if (!strcmp(fresh[i].id, scenes[j].id)) {
        fresh[i].scroll = scenes[j].scroll;
        fresh[i].zoom = scenes[j].zoom;
      }
  for (int i = 0; i < count; i++) {
    free(scenes[i].body);
  }
  memset(scenes, 0, sizeof scenes);
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
#endif
