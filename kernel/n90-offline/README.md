# Offline: the phone writes its own pages

Scenes come from an LLM on the laptop's side, so a phone with no connection
used to be frozen: it could only show pages it already had. Two pieces change
that, both measured on the phone on 23 October 2026.

- **`n90-scene`** (`scene.sh`) publishes a scene from the phone itself: the
  same release switch the laptop's `scene.py` makes, the renderer's own check,
  and the previous scenes back if the renderer rejects it. Any program on the
  phone can now put a page on the screen without the laptop.
- **`n90-story`** (`story.sh`) is the first such program: a small language
  model on the phone writes a short story and publishes it as the "Story"
  scene. The Wi-Fi keeper runs it once after ten minutes with no Wi-Fi and
  no laptop on the cable.

When the laptop next reaches the phone, it copies scenes the phone wrote into
the scene library (`scene.py adopt`, also run by the follower and before every
publish), so they survive the next reboot and appear in the library's history
as "Written on the phone".

## What a model can do on this phone

The A4 has one Cortex-A8 core at 800 MHz and 512 MB of RAM, all of it shared
with the RAM filesystem. llama2.c (Karpathy, MIT) runs Llama-architecture
models in plain C; its int8 runner with two changes for this phone
(`0001-runq-n90.patch`) is `n90-llm`:

- the int8 dot products use NEON (`vmull.s8`, `vpadal.s16`), which GCC did
  not do for the Cortex-A8;
- the token embeddings stay int8 and one row is dequantized per token,
  instead of a float copy of the whole table (37 MB for the 15M model, 65 MB
  for 42M).

The same seed gives the same text before and after the patch. Speeds on the
phone, nice 19, the screen blanked, 120-256 tokens:

| Model (TinyStories) | Format | Tokens a second | Memory |
| --- | --- | ---: | ---: |
| 15M | fp32, `run` | 3.4 | 60 MB file |
| 15M | int8, upstream `runq` | 4.3 | 17 MB file + 37 MB table |
| 15M | int8, `n90-llm` | 7.2 | 19 MB resident |
| 42M | int8, upstream `runq` | 2.3 | 44 MB file + 65 MB table |
| 42M | int8, `n90-llm` | 3.4 | 46 MB resident |

`n90-story` uses the 15M model: a story of about 250 tokens in 25-35 s, with
17 MB of model in RAM all the time. These models only write simple
children's stories; that is what they were trained on. A general model that
could answer questions or summarise is out of reach here: the 42M model
already runs at 3.4 tokens a second, and the smallest instruction-following
models, such as SmolLM2 at 135M parameters, are three times larger again
(about one token a second, an estimate from the table, not a measurement).

So most of what the phone can usefully show offline still has to be written
ahead, on the laptop's side, while there is a connection; the phone keeps
every scene in RAM until it reboots. What is new is that the phone can make
and publish pages by itself.

## Building and installing

```sh
make -C kernel/n90-offline    # output/offline: n90-llm, tokenizer.bin, stories15M-q80.bin
```

`quantize.py` turns the published fp32 checkpoint into llama2.c's int8
format (version 2) without PyTorch, with export.py's layout and arithmetic.
Sources and hashes are pinned in the Makefile: llama2.c `350e04fe` and
`stories15M.bin` from huggingface.co/karpathy/tinyllamas, both MIT.

The boot pass installs everything (`harness/phone_boot.py`,
`deploy_offline`): the model in `/opt/n90-offline`, `n90-scene` and
`n90-story` in `/usr/sbin`, and the laptop's time zone as `/etc/localtime`,
so pages the phone writes say local time.

```sh
n90-story --show          # on the phone: write a story now and show it
n90-scene put page.md     # publish any scene marked "source: phone ..."
```

## On the phone, 23 October 2026

`n90-story` wrote a three-paragraph story in 27 s and published it as release
`phone-835fe3b20cca`; Soy reloaded (`bundle_loads` 2, no failures) and listed
`story` after Boris's scenes. `scene.py sync` from the laptop then committed
it to the scene library as "Written on the phone: story" and found the phone
in step. The offline trigger was exercised with a fake clock and fake
connectivity: one story ten minutes into each stretch offline, none while
Wi-Fi or the laptop answered. The boot pass after the next reboot installed
the model and both tools (`offline_installed`), and the phone's clock read
NZDT.
