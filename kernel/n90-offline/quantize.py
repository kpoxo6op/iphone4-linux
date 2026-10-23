#!/usr/bin/env python3
"""Turn a llama2.c fp32 checkpoint (version 0) into its Q8_0 format (version 2).

llama2.c's own export.py needs PyTorch and the training checkpoint; this reads
the published .bin directly. Same layout and arithmetic as export.py's
version2_export: rmsnorm weights stay fp32, every other weight is quantized
to int8 in groups of 64 with one fp32 scale per group.

    python3 quantize.py stories42M.bin stories42M-q80.bin
"""
import struct
import sys

import numpy as np

source, target = sys.argv[1], sys.argv[2]
raw = open(source, 'rb').read()
dim, hidden, layers, heads, kv_heads, vocab, seq = struct.unpack('7i', raw[:28])
shared = vocab > 0
vocab = abs(vocab)
head = dim // heads
f = np.frombuffer(raw, dtype=np.float32, offset=28)
at = 0


def take(*shape):
    global at
    n = int(np.prod(shape))
    out = f[at:at + n].reshape(shape)
    at += n
    return out


embed = take(vocab, dim)
rms_att = take(layers, dim)
wq = take(layers, dim, dim)
wk = take(layers, kv_heads * head, dim)
wv = take(layers, kv_heads * head, dim)
wo = take(layers, dim, dim)
rms_ffn = take(layers, dim)
w1 = take(layers, hidden, dim)
w2 = take(layers, dim, hidden)
w3 = take(layers, hidden, dim)
rms_final = take(dim)
take(seq, head // 2)  # the legacy format's RoPE tables, unused by runq.c
take(seq, head // 2)
wcls = None if shared else take(vocab, dim)
assert at == f.size, f'{f.size - at} floats left over'

group = 64
while dim % group:
    group //= 2


def q80(w):
    w = w.reshape(-1, group).astype(np.float32)
    scale = np.abs(w).max(axis=1) / 127.0
    q = np.round(w / np.where(scale == 0, 1, scale)[:, None]).astype(np.int8)
    return q.tobytes() + scale.astype(np.float32).tobytes()


with open(target, 'wb') as out:
    out.write(struct.pack('I', 0x616b3432) + struct.pack('i', 2))
    out.write(struct.pack('7i', dim, hidden, layers, heads, kv_heads, vocab, seq))
    out.write(struct.pack('B', int(shared)) + struct.pack('i', group))
    out.write(b'\0' * (256 - out.tell()))
    for norm in (rms_att, rms_ffn, rms_final):
        out.write(norm.astype(np.float32).tobytes())
    out.write(q80(embed))
    for weights in (wq, wk, wv, wo, w1, w2, w3):
        for layer in weights:
            out.write(q80(layer))
    if wcls is not None:
        out.write(q80(wcls))
print(f'{target}: dim {dim}, {layers} layers, vocab {vocab}, group {group}')
