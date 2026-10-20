#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <ghostty/vt.h>
#include <poll.h>
#include <pty.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>

/* Integration probe: actual shell -> PTY -> Ghostty -> public render state.
 * No framebuffer access and no credentials. A failed contract exits nonzero.
 */
static uint32_t grid[14][28];
static GhosttyStyle first_style;

static double monotonic_ms(void) {
  struct timespec ts;
  assert(clock_gettime(CLOCK_MONOTONIC, &ts) == 0);
  return ts.tv_sec * 1000.0 + ts.tv_nsec / 1000000.0;
}

static void snapshot(GhosttyTerminal terminal, GhosttyRenderState state) {
  assert(ghostty_render_state_update(state, terminal) == GHOSTTY_SUCCESS);
  GhosttyRenderStateRowIterator rows = NULL;
  GhosttyRenderStateRowCells cells = NULL;
  assert(ghostty_render_state_row_iterator_new(NULL, &rows) == GHOSTTY_SUCCESS);
  assert(ghostty_render_state_row_cells_new(NULL, &cells) == GHOSTTY_SUCCESS);
  assert(ghostty_render_state_get(state, GHOSTTY_RENDER_STATE_DATA_ROW_ITERATOR,
                                 &rows) == GHOSTTY_SUCCESS);
  uint16_t y;
  while (ghostty_render_state_row_iterator_next_dirty(rows, &y)) {
    assert(y < 14);
    assert(ghostty_render_state_row_get(rows, GHOSTTY_RENDER_STATE_ROW_DATA_CELLS,
                                       &cells) == GHOSTTY_SUCCESS);
    unsigned x = 0;
    while (ghostty_render_state_row_cells_next(cells)) {
      assert(x < 28);
      uint32_t len = 0;
      assert(ghostty_render_state_row_cells_get(
                 cells, GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_GRAPHEMES_LEN,
                 &len) == GHOSTTY_SUCCESS);
      grid[y][x] = 0;
      if (len) {
        uint32_t *cp = calloc(len, sizeof *cp);
        if (!cp)
          fprintf(stderr, "grapheme allocation: row=%u col=%u len=%u errno=%d\n",
                  y, x, len, errno);
        assert(cp);
        assert(ghostty_render_state_row_cells_get(
                   cells, GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_GRAPHEMES_BUF,
                   cp) == GHOSTTY_SUCCESS);
        grid[y][x] = cp[0];
        free(cp);
      }
      if (!x && !y) {
        first_style = (GhosttyStyle)GHOSTTY_INIT_SIZED(GhosttyStyle);
        assert(ghostty_render_state_row_cells_get(
                   cells, GHOSTTY_RENDER_STATE_ROW_CELLS_DATA_STYLE,
                   &first_style) == GHOSTTY_SUCCESS);
      }
      x++;
    }
  }
  ghostty_render_state_row_cells_free(cells);
  ghostty_render_state_row_iterator_free(rows);
}

int main(void) {
  alarm(15);
  double started = monotonic_ms();
  GhosttyTerminal terminal = NULL;
  GhosttyRenderState state = NULL;
  assert(ghostty_terminal_new(NULL, &terminal, 28, 14) == GHOSTTY_SUCCESS);
  assert(ghostty_render_state_new(NULL, &state) == GHOSTTY_SUCCESS);
  size_t scrollback_limit = 256 * 1024;
  assert(ghostty_terminal_set(terminal, GHOSTTY_TERMINAL_OPT_SCROLLBACK_MAX_BYTES,
                              &scrollback_limit) == GHOSTTY_SUCCESS);

  int master, slave;
  struct winsize size = {.ws_row = 14, .ws_col = 28};
  assert(openpty(&master, &slave, NULL, NULL, &size) == 0);
  struct termios raw;
  assert(tcgetattr(slave, &raw) == 0);
  cfmakeraw(&raw);
  assert(tcsetattr(slave, TCSANOW, &raw) == 0);
  pid_t child = fork();
  assert(child >= 0);
  if (!child) {
    close(master);
    assert(setsid() >= 0);
    assert(ioctl(slave, TIOCSCTTY, 0) == 0);
    assert(dup2(slave, 0) == 0);
    assert(dup2(slave, 1) == 1);
    assert(dup2(slave, 2) == 2);
    if (slave > 2)
      close(slave);
    execl("/bin/sh", "sh", "-c",
          "printf '\\033[2J\\033[H\\033[1;32mПривет, iPhone\\033[0m"
          "\\r\\nold\\r\\033[2Knew\\r\\nbox: ─│"
          "\\033[?1049h\\033[2J\\033[Htemporary\\033[?1049l'",
          (char *)NULL);
    _exit(127);
  }
  close(slave);
  size_t bytes = 0;
  double parse_ms = 0;
  for (;;) {
    struct pollfd p = {master, POLLIN, 0};
    assert(poll(&p, 1, 5000) > 0);
    /* Deliberately split UTF-8 and escape sequences across tiny reads. */
    uint8_t buf[3];
    ssize_t n = read(master, buf, sizeof buf);
    if (!n || (n < 0 && errno == EIO))
      break;
    assert(n > 0);
    double before = monotonic_ms();
    ghostty_terminal_vt_write(terminal, buf, (size_t)n);
    parse_ms += monotonic_ms() - before;
    bytes += (size_t)n;
  }
  close(master);
  int status;
  assert(waitpid(child, &status, 0) == child);
  assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);

  snapshot(terminal, state);
  const uint32_t russian[] = {0x41f, 0x440, 0x438, 0x432, 0x435, 0x442};
  assert(!memcmp(grid[0], russian, sizeof russian));
  assert(grid[0][8] == 'i' && grid[0][13] == 'e' && grid[0][14] == 0);
  assert(first_style.bold);
  assert(first_style.fg_color.tag == GHOSTTY_STYLE_COLOR_PALETTE);
  assert(first_style.fg_color.value.palette == 2);
  assert(grid[1][0] == 'n' && grid[1][1] == 'e' && grid[1][2] == 'w');
  assert(grid[2][5] == 0x2500 && grid[2][6] == 0x2502);

  assert(ghostty_render_state_clean(state) == GHOSTTY_SUCCESS);
  assert(ghostty_render_state_update(state, terminal) == GHOSTTY_SUCCESS);
  GhosttyRenderStateDirty dirty;
  assert(ghostty_render_state_get(state, GHOSTTY_RENDER_STATE_DATA_DIRTY,
                                 &dirty) == GHOSTTY_SUCCESS);
  assert(dirty == GHOSTTY_RENDER_STATE_DIRTY_FALSE);
  const char update[] = "\033[2;1HN";
  ghostty_terminal_vt_write(terminal, (const uint8_t *)update, strlen(update));
  snapshot(terminal, state);
  assert(grid[1][0] == 'N' && grid[1][1] == 'e');

  assert(ghostty_terminal_resize(terminal, 26, 14, 22, 48) == GHOSTTY_SUCCESS);
  snapshot(terminal, state);
  assert(!memcmp(grid[0], russian, sizeof russian));
  assert(grid[1][0] == 'N');

  GhosttyTerminalMemoryUsage memory =
      GHOSTTY_INIT_SIZED(GhosttyTerminalMemoryUsage);
  assert(ghostty_terminal_get(terminal, GHOSTTY_TERMINAL_DATA_MEMORY_USAGE,
                             &memory) == GHOSTTY_SUCCESS);
  struct rusage usage;
  assert(getrusage(RUSAGE_SELF, &usage) == 0);
  printf("{\"passed\":true,\"pty_bytes\":%zu,\"checks\":[\"real_shell_pty\","
         "\"split_utf8_cyrillic\",\"ansi_styles\",\"cursor_erase\","
         "\"box_drawing\",\"alternate_screen_restore\",\"clean_frame\","
         "\"incremental_update\",\"resize\"],\"parse_ms\":%.3f,"
         "\"total_ms\":%.3f,\"peak_rss_kib\":%ld,"
         "\"terminal_page_resident_bytes\":%llu}\n",
         bytes, parse_ms, monotonic_ms() - started, usage.ru_maxrss,
         (unsigned long long)(memory.primary_resident_bytes +
                              memory.alternate_resident_bytes));
  ghostty_render_state_free(state);
  ghostty_terminal_free(terminal);
  return 0;
}
