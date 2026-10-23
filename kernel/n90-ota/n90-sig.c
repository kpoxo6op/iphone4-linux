// SPDX-License-Identifier: GPL-2.0
/*
 * n90-sig: Ed25519 signatures for the phone's releases (kernel/n90-ota).
 *
 *   n90-sig keygen SECRET PUBLIC   new key pair (laptop; the secret stays in
 *                                  .runtime/phone/private)
 *   n90-sig sign SECRET FILE       write FILE.sig
 *   n90-sig verify PUBLIC FILE     check FILE.sig; exit 0 only if it is good
 *
 * Keys and signatures are hex on one line. The arithmetic is TweetNaCl
 * (Bernstein et al., public domain), compiled in unchanged.
 */
#include <fcntl.h>
#include <sys/stat.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "tweetnacl.h"

void randombytes(unsigned char *out, unsigned long long n)
{
	int fd = open("/dev/urandom", O_RDONLY);

	if (fd < 0 || read(fd, out, n) != (ssize_t)n) {
		perror("/dev/urandom");
		exit(1);
	}
	close(fd);
}

static unsigned char *slurp(const char *path, unsigned long long *n)
{
	FILE *f = fopen(path, "rb");
	unsigned char *buf = NULL;
	long size;

	if (!f || fseek(f, 0, SEEK_END) || (size = ftell(f)) < 0 || fseek(f, 0, SEEK_SET) ||
	    !(buf = malloc(size + crypto_sign_BYTES)) ||
	    fread(buf + crypto_sign_BYTES, 1, size, f) != (size_t)size) {
		fprintf(stderr, "n90-sig: cannot read %s\n", path);
		exit(1);
	}
	fclose(f);
	*n = size;
	return buf;
}

static void read_hex(const char *path, unsigned char *out, size_t n)
{
	FILE *f = fopen(path, "r");
	unsigned int byte;

	for (size_t i = 0; i < n; i++)
		if (!f || fscanf(f, "%2x", &byte) != 1) {
			fprintf(stderr, "n90-sig: %s is not a %zu-byte hex key\n", path, n);
			exit(1);
		} else {
			out[i] = byte;
		}
	fclose(f);
}

static void write_hex(const char *path, const unsigned char *in, size_t n)
{
	FILE *f = fopen(path, "w");

	if (!f) {
		perror(path);
		exit(1);
	}
	for (size_t i = 0; i < n; i++)
		fprintf(f, "%02x", in[i]);
	fputc('\n', f);
	if (fclose(f)) {
		perror(path);
		exit(1);
	}
}

int main(int argc, char **argv)
{
	unsigned char pk[crypto_sign_PUBLICKEYBYTES], sk[crypto_sign_SECRETKEYBYTES];
	unsigned long long n, smlen, mlen;
	char sig[4096];

	if (argc == 4 && !strcmp(argv[1], "keygen")) {
		umask(077);
		crypto_sign_keypair(pk, sk);
		write_hex(argv[2], sk, sizeof sk);
		write_hex(argv[3], pk, sizeof pk);
		return 0;
	}
	if (argc != 4 || (strcmp(argv[1], "sign") && strcmp(argv[1], "verify"))) {
		fprintf(stderr, "usage: n90-sig keygen SECRET PUBLIC | sign SECRET FILE | "
			"verify PUBLIC FILE\n");
		return 2;
	}
	snprintf(sig, sizeof sig, "%s.sig", argv[3]);
	unsigned char *buf = slurp(argv[3], &n), *sm, *m;

	if (!strcmp(argv[1], "sign")) {
		read_hex(argv[2], sk, sizeof sk);
		sm = malloc(n + crypto_sign_BYTES);
		if (!sm || crypto_sign(sm, &smlen, buf + crypto_sign_BYTES, n, sk))
			return 1;
		write_hex(sig, sm, crypto_sign_BYTES);
		return 0;
	}
	/* crypto_sign_open wants the signature in front of the message. */
	read_hex(argv[2], pk, sizeof pk);
	read_hex(sig, buf, crypto_sign_BYTES);
	m = malloc(n + crypto_sign_BYTES);
	if (!m || crypto_sign_open(m, &mlen, buf, n + crypto_sign_BYTES, pk) || mlen != n) {
		fprintf(stderr, "n90-sig: bad signature on %s\n", argv[3]);
		return 1;
	}
	return 0;
}
