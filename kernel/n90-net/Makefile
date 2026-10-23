# The phone's firewall: a static nft and the netfilter modules of the running
# lean kernel (e899dceb), built with the Buildroot armv7 toolchain that built
# that kernel. `make` leaves everything deploy.py installs in output/net.
TOOLCHAIN ?= $(HOME)/code/iphone4-linux-workers/kernel/.cache/toolchain/armv7-eabihf--glibc--stable-2025.08-1/bin
HOST := arm-buildroot-linux-gnueabihf
# The lean kernel's patched source and build trees (kernel/n90-wifi/README.md).
KSRC ?= $(HOME)/code/iphone4-linux-touch/.cache/kernel-fast-src
KBUILD ?= $(HOME)/code/iphone4-linux-touch/.cache/kernel-fast-build
OUT ?= ../../output/net
CACHE ?= ../../.cache/net
DOWNLOADS ?= ../../.cache/downloads/netfilter

# netfilter.org releases, signed by the Netfilter Core Team
# (libmnl: 37D9 64AC C049 81C7 5500 FB9B D55D 978A 8A14 20E4;
#  libnftnl, nftables: 8C5F 7146 A175 7A65 E242 2A94 D70D 1A66 6ACF 2B21).
URL := https://www.netfilter.org/projects
LIBMNL := libmnl-1.0.5.tar.bz2
LIBMNL_SHA256 := 274b9b919ef3152bfb3da3a13c950dd60d6e2bcd54230ffeca298d03b40d0525
LIBNFTNL := libnftnl-1.3.2.tar.xz
LIBNFTNL_SHA256 := c97abc3409f8fa396b4462b2bb7f147a3a47a4ddc97cfa0b2f18890c9cfde8b0
NFTABLES := nftables-1.1.7.tar.xz
NFTABLES_SHA256 := a6fbf060d8d4fff001517a2b94f356bb4366bfbf0ba366366f9d27cc38caa58f

MODULES := net/netfilter/nfnetlink.ko net/netfilter/nf_tables.ko \
	net/ipv4/netfilter/nf_defrag_ipv4.ko net/ipv6/netfilter/nf_defrag_ipv6.ko \
	net/netfilter/nf_conntrack.ko net/netfilter/nft_ct.ko

export PATH := $(TOOLCHAIN):$(PATH)

all: $(OUT)/nft modules

$(DOWNLOADS)/%:
	mkdir -p $(DOWNLOADS)
	curl -sSfL -o $@.part $(URL)/$(firstword $(subst -, ,$*))/files/$*
	mv $@.part $@

define unpack
	echo "$(2)  $(DOWNLOADS)/$(1)" | sha256sum -c --quiet
	tar -xf $(DOWNLOADS)/$(1) -C $(CACHE)
endef

# Static, without the interactive shell, JSON or GMP (mini-gmp instead).
$(OUT)/nft: $(DOWNLOADS)/$(LIBMNL) $(DOWNLOADS)/$(LIBNFTNL) $(DOWNLOADS)/$(NFTABLES)
	rm -rf $(CACHE) && mkdir -p $(CACHE)/sysroot $(OUT)
	$(call unpack,$(LIBMNL),$(LIBMNL_SHA256))
	$(call unpack,$(LIBNFTNL),$(LIBNFTNL_SHA256))
	$(call unpack,$(NFTABLES),$(NFTABLES_SHA256))
	set -e; S=$$(realpath $(CACHE)/sysroot); \
	export PKG_CONFIG_LIBDIR=$$S/lib/pkgconfig PKG_CONFIG_PATH=$$S/lib/pkgconfig; \
	cd $(CACHE)/libmnl-1.0.5 && ./configure -q --host=$(HOST) --prefix=$$S \
		--enable-static --disable-shared CFLAGS=-Os && $(MAKE) -s -j2 install; \
	cd ../libnftnl-1.3.2 && ./configure -q --host=$(HOST) --prefix=$$S \
		--enable-static --disable-shared CFLAGS=-Os && $(MAKE) -s -j2 install; \
	cd ../nftables-1.1.7 && ./configure -q --host=$(HOST) --prefix=/usr \
		--sysconfdir=/etc --enable-static --disable-shared --with-mini-gmp \
		--without-cli --without-json --disable-man-doc CFLAGS=-Os && \
	$(MAKE) -s -j2 LDFLAGS=-all-static
	$(HOST)-strip -o $@ $(CACHE)/nftables-1.1.7/src/nft

# CONFIG_MODVERSIONS is off, so the modules are tied to this exact build by
# the kernel's build stamp, which n90-firewall checks before loading them.
modules:
	mkdir -p $(OUT)
	$(MAKE) -C $(KSRC) O=$(KBUILD) ARCH=arm CROSS_COMPILE=$(HOST)- \
		KBUILD_MODPOST_WARN=1 -j2 $(MODULES)
	for m in $(MODULES); do \
		$(HOST)-strip --strip-debug -o $(OUT)/$$(basename $$m) $(KBUILD)/$$m; done
	sed -n 's/^#define UTS_VERSION "\(.*\)"/\1/p' \
		$(KBUILD)/include/generated/utsversion.h > $(OUT)/kernel

.PHONY: all modules clean
clean:
	rm -rf $(OUT) $(CACHE)
