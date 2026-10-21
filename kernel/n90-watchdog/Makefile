# Cross-build the A4 watchdog keeper with the knownboot toolchain.
TOOLCHAIN ?= $(HOME)/code/iphone4-linux-workers/kernel/.cache/toolchain/armv7-eabihf--glibc--stable-2025.08-1/bin
CC := $(TOOLCHAIN)/arm-buildroot-linux-gnueabihf-gcc
OUT ?= ../../output/watchdog

$(OUT)/n90-wdt: n90-wdt.c
	mkdir -p $(OUT)
	$(CC) -O2 -Wall -static -o $@ $<

.PHONY: clean
clean:
	rm -f $(OUT)/n90-wdt
