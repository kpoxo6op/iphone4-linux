# Cross-build the Wi-Fi tool with the Buildroot armv7 toolchain that built
# the knownboot kernel (as kernel/n90-battery does).
TOOLCHAIN ?= $(HOME)/code/iphone4-linux-workers/kernel/.cache/toolchain/armv7-eabihf--glibc--stable-2025.08-1/bin
CC := $(TOOLCHAIN)/arm-buildroot-linux-gnueabihf-gcc
OUT ?= ../../output/wifi

$(OUT)/n90-wifi: n90-wifi.c
	mkdir -p $(OUT)
	$(CC) -O2 -Wall -Wextra -static -o $@ $<

.PHONY: clean
clean:
	rm -f $(OUT)/n90-wifi
