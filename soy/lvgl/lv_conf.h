#ifndef LV_CONF_H
#define LV_CONF_H
#define LV_COLOR_FORMAT_DEFAULT LV_COLOR_FORMAT_XRGB8888
#define LV_USE_STDLIB_MALLOC LV_STDLIB_CLIB
#define LV_USE_STDLIB_STRING LV_STDLIB_CLIB
#define LV_USE_STDLIB_SPRINTF LV_STDLIB_CLIB
#define LV_USE_OS LV_OS_NONE
#if defined(__ARM_NEON)
#define LV_USE_DRAW_SW_ASM LV_DRAW_SW_ASM_NEON
#endif
#define LV_DEF_REFR_PERIOD 8
#define LV_DPI_DEF 220
/* Keep clock times intact at a line break. */
#define LV_TXT_BREAK_CHARS " ,.;-_)]}"
#define LV_USE_FLOAT 1
#define LV_USE_GESTURE_RECOGNITION 1
#define LV_USE_THEME_DEFAULT 0
#define LV_USE_THEME_SIMPLE 0
#define LV_USE_THEME_MONO 0
#define LV_USE_LOG 1
#define LV_LOG_LEVEL LV_LOG_LEVEL_WARN
#define LV_LOG_PRINTF 1
#define LV_BUILD_EXAMPLES 0
#define LV_BUILD_DEMOS 0
#define LV_USE_THORVG 0
#define LV_USE_THORVG_INTERNAL 0
#define LV_USE_SYSMON 0
#define LV_USE_PERF_MONITOR 0
#define LV_USE_EVDEV 0
#define LV_USE_ASSERT_MALLOC 1
#define LV_USE_ASSERT_NULL 1
#define LV_DRAW_BUF_STRIDE_ALIGN 1
#define LV_FONT_DEFAULT &lv_font_montserrat_14
#define LV_USE_SPAN 1
#define LV_USE_SNAPSHOT 1
/* Snapshot buffers are owned by views; do not retain decoder references. */
#define LV_CACHE_DEF_SIZE 0
#define LV_IMAGE_HEADER_CACHE_DEF_CNT 0
#define LV_USE_CHART 1
#endif
