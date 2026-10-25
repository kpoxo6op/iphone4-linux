// SPDX-License-Identifier: GPL-2.0-only
/* N90 I2C2: Apple's /arm-io/i2c2 gives SDA 0x0907 and SCL 0x0a00.
 * The existing A4 GPIO encoding is bank * 8 + pin: 79 and 80.
 * Register the standard Linux i2c-gpio driver, as the working I2C0 does.
 * No sensor power, PMU, scanout, UART or unrelated GPIO writes here.
 */
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/platform_data/i2c-gpio.h>
#include <linux/gpio/machine.h>
#include <linux/jiffies.h>

static char *chip = "bfa00000.gpio";
module_param(chip, charp, 0444);
MODULE_PARM_DESC(chip, "Exact live A4 GPIO chip label");
static struct platform_device *bus;
static struct gpiod_lookup_table pins = {
 .dev_id = "i2c-gpio.2",
 .table = {
  GPIO_LOOKUP("bfa00000.gpio", 79, "sda", GPIO_ACTIVE_HIGH),
  GPIO_LOOKUP("bfa00000.gpio", 80, "scl", GPIO_ACTIVE_HIGH),
  { }
 }
};
static struct i2c_gpio_platform_data timing = {.udelay = 5, .timeout = HZ / 10};
static int __init n90_i2c2_init(void)
{
 pins.table[0].key = chip; pins.table[1].key = chip;
 gpiod_add_lookup_table(&pins);
 bus = platform_device_register_data(NULL, "i2c-gpio", 2, &timing, sizeof(timing));
 if (IS_ERR(bus)) { gpiod_remove_lookup_table(&pins); return PTR_ERR(bus); }
 pr_info("n90-i2c2: registered i2c-gpio on SDA79/SCL80; verify adapter and sensor IDs\n");
 return 0;
}
static void __exit n90_i2c2_exit(void)
{
 platform_device_unregister(bus);
 gpiod_remove_lookup_table(&pins);
}
module_init(n90_i2c2_init);
module_exit(n90_i2c2_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("N90 sensor I2C2 through the standard GPIO I2C adapter");
