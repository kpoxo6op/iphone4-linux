# The phone's offline writer (README.md): llama2.c's int8 runner with this
# phone's patch, and Karpathy's 15M TinyStories model quantized to int8.
# Built with the Buildroot armv7 toolchain, as kernel/n90-battery is.
TOOLCHAIN ?= $(HOME)/code/iphone4-linux-workers/kernel/.cache/toolchain/armv7-eabihf--glibc--stable-2025.08-1/bin
CC := $(TOOLCHAIN)/arm-buildroot-linux-gnueabihf-gcc
OUT ?= ../../output/offline
CACHE ?= ../../.cache/n90-offline

# llama2.c (MIT), the commit of 29 May 2024.
LLAMA2C := 350e04fe35433e6d2941dce5a1f53308f87058eb
LLAMA2C_SHA256 := 9210e104192375f2c156fd24a84d2692c6b199f8ebbc2337551842c03cc1ddce
TOKENIZER_SHA256 := 50a52ef822ee9e83de5ce9d0be0a025a773d019437f58b5ff9dcafb063ece361
# huggingface.co/karpathy/tinyllamas (MIT).
MODEL_SHA256 := cd590644d963867a2b6e5a1107f51fad663c41d79c149fbecbbb1f95fa81f49a

all: $(OUT)/n90-llm $(OUT)/tokenizer.bin $(OUT)/stories15M-q80.bin

$(CACHE)/llama2.c.tar.gz:
	mkdir -p $(CACHE)
	curl -sSfL -o $@.part https://codeload.github.com/karpathy/llama2.c/tar.gz/$(LLAMA2C)
	echo "$(LLAMA2C_SHA256)  $@.part" | sha256sum -c --quiet
	mv $@.part $@

$(CACHE)/src/runq.c: $(CACHE)/llama2.c.tar.gz 0001-runq-n90.patch
	rm -rf $(CACHE)/src && mkdir -p $(CACHE)/src
	tar -xzf $< -C $(CACHE)/src --strip-components=1
	patch -s -d $(CACHE)/src -p1 < 0001-runq-n90.patch

$(OUT)/n90-llm: $(CACHE)/src/runq.c
	mkdir -p $(OUT)
	$(CC) -Ofast -mcpu=cortex-a8 -mfpu=neon -mfloat-abi=hard -static -s -o $@ $< -lm

$(OUT)/tokenizer.bin: $(CACHE)/src/runq.c
	echo "$(TOKENIZER_SHA256)  $(CACHE)/src/tokenizer.bin" | sha256sum -c --quiet
	mkdir -p $(OUT)
	cp $(CACHE)/src/tokenizer.bin $@

$(CACHE)/stories15M.bin:
	mkdir -p $(CACHE)
	curl -sSfL -o $@.part https://huggingface.co/karpathy/tinyllamas/resolve/main/stories15M.bin
	echo "$(MODEL_SHA256)  $@.part" | sha256sum -c --quiet
	mv $@.part $@

$(OUT)/stories15M-q80.bin: $(CACHE)/stories15M.bin quantize.py
	mkdir -p $(OUT)
	python3 -I quantize.py $< $@

.PHONY: all clean
clean:
	rm -rf $(CACHE) $(OUT)/n90-llm $(OUT)/tokenizer.bin $(OUT)/stories15M-q80.bin
