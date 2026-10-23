# The phone's clock keeper, built against musl (Buildroot's ext-toolchain from
# the qemu lane, as Soy's armv7 build is) so its DNS resolver works in a
# static binary.
TOOLCHAIN ?= $(HOME)/code/iphone4-linux-workers/qemu/output/buildroot/host/bin
CC := $(TOOLCHAIN)/arm-linux-gcc
OUT ?= ../../output/time

$(OUT)/n90-time: n90-time.c
	mkdir -p $(OUT)
	$(CC) -O2 -Wall -Wextra -static -s -o $@ $< -lm

.PHONY: clean
clean:
	rm -f $(OUT)/n90-time
