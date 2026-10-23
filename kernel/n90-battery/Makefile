# Cross-build the N90 battery reader with the Buildroot armv7 toolchain that
# built the knownboot kernel (as kernel/n90-touch does).
TOOLCHAIN ?= $(HOME)/code/iphone4-linux-workers/kernel/.cache/toolchain/armv7-eabihf--glibc--stable-2025.08-1/bin
CC := $(TOOLCHAIN)/arm-buildroot-linux-gnueabihf-gcc
OUT ?= ../../output/battery

$(OUT)/n90-battery: n90-battery.c
	mkdir -p $(OUT)
	$(CC) -O2 -Wall -Wextra -static -o $@ $< -lm

.PHONY: clean
clean:
	rm -f $(OUT)/n90-battery
