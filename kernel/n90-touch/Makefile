# Cross-build the N90 touch tool. TOOLCHAIN is the Buildroot armv7 toolchain
# that built the knownboot kernel.
TOOLCHAIN ?= $(HOME)/code/iphone4-linux-workers/kernel/.cache/toolchain/armv7-eabihf--glibc--stable-2025.08-1/bin
CC := $(TOOLCHAIN)/arm-buildroot-linux-gnueabihf-gcc
OUT ?= ../../output/touch

$(OUT)/n90-touch: n90-touch.c
	mkdir -p $(OUT)
	$(CC) -O2 -Wall -static -o $@ $<

.PHONY: clean
clean:
	rm -f $(OUT)/n90-touch
