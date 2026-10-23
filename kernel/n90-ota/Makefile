# Over-the-air releases (README.md): n90-sig for the phone (musl, as
# kernel/n90-time) and for this computer, which signs, and a wget that
# speaks HTTPS for the phone.
TOOLCHAIN ?= $(HOME)/code/iphone4-linux-workers/qemu/output/buildroot/host/bin
CC := $(TOOLCHAIN)/arm-linux-gcc
HOSTCC ?= cc
OUT ?= ../../output/ota
CACHE ?= ../../.cache/n90-ota
# TweetNaCl, public domain, from its authors' site.
NACL := https://tweetnacl.cr.yp.to/20140427
NACL_C_SHA256 := 02e65bc3013ff2168983365e55906bc783c4c7e0a60d8100f17bb303a17175c4
NACL_H_SHA256 := 43f29ad721d9927b747b0100ab4160c119e7bb180c7c98a66e4bf79d31244287

# BusyBox 1.38.0, the phone's own version, built as nothing but wget with
# its built-in TLS: the phone's busybox has no HTTPS.
BUSYBOX := https://busybox.net/downloads/busybox-1.38.0.tar.bz2
BUSYBOX_SHA256 := 34f9ea6ff8636f2c9241153b9114eefa9e65674a45318ae1ef95bb5f31c53bb2
BUSYBOX_OPTIONS := WGET FEATURE_WGET_HTTPS FEATURE_WGET_TIMEOUT FEATURE_WGET_LONG_OPTIONS \
	TLS STATIC LFS

all: $(OUT)/n90-sig $(OUT)/n90-sig-host $(OUT)/wget

$(CACHE)/busybox-1.38.0.tar.bz2:
	mkdir -p $(CACHE)
	curl -sSfL -o $@.part $(BUSYBOX)
	echo "$(BUSYBOX_SHA256)  $@.part" | sha256sum -c --quiet
	mv $@.part $@

$(OUT)/wget: $(CACHE)/busybox-1.38.0.tar.bz2
	echo "$(BUSYBOX_SHA256)  $<" | sha256sum -c --quiet
	rm -rf $(CACHE)/busybox && mkdir -p $(CACHE)/busybox $(OUT)
	tar -xjf $< -C $(CACHE)/busybox --strip-components=1
	$(MAKE) -s -C $(CACHE)/busybox allnoconfig > /dev/null
	cd $(CACHE)/busybox && for o in $(BUSYBOX_OPTIONS); do \
		sed -i "s/^# CONFIG_$$o is not set/CONFIG_$$o=y/" .config; done && \
		yes "" | $(MAKE) -s oldconfig > /dev/null
	$(MAKE) -s -C $(CACHE)/busybox -j2 CROSS_COMPILE=$(TOOLCHAIN)/arm-linux-
	cp $(CACHE)/busybox/busybox $@

$(CACHE)/tweetnacl.c $(CACHE)/tweetnacl.h:
	mkdir -p $(CACHE)
	curl -sSfL -o $(CACHE)/tweetnacl.c.part $(NACL)/tweetnacl.c
	curl -sSfL -o $(CACHE)/tweetnacl.h.part $(NACL)/tweetnacl.h
	echo "$(NACL_C_SHA256)  $(CACHE)/tweetnacl.c.part" | sha256sum -c --quiet
	echo "$(NACL_H_SHA256)  $(CACHE)/tweetnacl.h.part" | sha256sum -c --quiet
	mv $(CACHE)/tweetnacl.c.part $(CACHE)/tweetnacl.c
	mv $(CACHE)/tweetnacl.h.part $(CACHE)/tweetnacl.h

$(OUT)/n90-sig: n90-sig.c $(CACHE)/tweetnacl.c
	mkdir -p $(OUT)
	$(CC) -O2 -Wall -static -s -I$(CACHE) -o $@ n90-sig.c $(CACHE)/tweetnacl.c

$(OUT)/n90-sig-host: n90-sig.c $(CACHE)/tweetnacl.c
	mkdir -p $(OUT)
	$(HOSTCC) -O2 -Wall -I$(CACHE) -o $@ n90-sig.c $(CACHE)/tweetnacl.c

.PHONY: all clean
clean:
	rm -rf $(OUT)/n90-sig $(OUT)/n90-sig-host $(OUT)/wget
