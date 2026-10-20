CC ?= cc
CFLAGS ?= -O2 -std=c11 -Wall -Wextra
LDLIBS = -lm
.PHONY: all touch legacy clean
all: touch
touch:
	python3 tools/build_touch.py --target native
legacy: build/soy
build/soy: src/soy.c src/scene_data.h
	mkdir -p build
	$(CC) $(CFLAGS) $(LDFLAGS) $< -o $@ $(LDLIBS)
clean:
	rm -f build/soy
