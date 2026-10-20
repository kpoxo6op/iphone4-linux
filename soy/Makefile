CC ?= cc
CFLAGS ?= -O2 -std=c11 -Wall -Wextra
LDLIBS = -lm
.PHONY: all clean
all: build/soy
build/soy: src/soy.c
	mkdir -p build
	$(CC) $(CFLAGS) $(LDFLAGS) $< -o $@ $(LDLIBS)
clean:
	rm -f build/soy
