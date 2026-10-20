#!/usr/bin/env python3
"""Build pinned LVGL + Pixman. Downloads stay in .cache; no host installs."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess as sp
import tarfile
import urllib.request

p = argparse.ArgumentParser()
p.add_argument("--target", choices=["native", "armv7"], default="native")
p.add_argument("--toolchain", type=Path, help="ARM musl toolchain bin directory")
p.add_argument(
    "--build-tools",
    type=Path,
    help="Directory containing Meson and Ninja; defaults to toolchain or PATH",
)
p.add_argument("--sanitize", action="store_true")
a = p.parse_args()
root = Path(__file__).resolve().parents[2]
if a.sanitize and a.target != "native":
    p.error("Sanitizers run on the native host")
tool = a.toolchain.resolve() if a.toolchain else None
if a.target == "armv7":
    if not tool:
        p.error("--toolchain is required for armv7")
    for name in ("arm-linux-gcc", "arm-linux-g++", "arm-linux-ar", "arm-linux-strip"):
        if not (tool / name).is_file():
            p.error(f"Missing {name}")


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def source(filename, directory):
    pin = json.loads((root / "soy/lvgl" / filename).read_text())
    cache = root / ".cache" / directory
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / pin["url"].rsplit("/", 1)[1]
    # Keep the established LVGL cache filename, independent of the commit URL.
    if directory == "lvgl":
        archive = cache / f"lvgl-{pin['version']}.tar.gz"
    if not archive.exists():
        temporary = archive.with_suffix(".download")
        with (
            urllib.request.urlopen(pin["url"], timeout=60) as r,
            temporary.open("wb") as f,
        ):
            shutil.copyfileobj(r, f)
        if digest(temporary) != pin["sha256"]:
            temporary.unlink()
            raise SystemExit(f"{directory} archive hash mismatch")
        temporary.rename(archive)
    if digest(archive) != pin["sha256"]:
        raise SystemExit(f"{directory} archive hash mismatch")
    folder = cache / f"{directory}-{pin.get('revision', pin['version'])}"
    if not folder.exists():
        with tarfile.open(archive) as tar:
            tar.extractall(cache, filter="data")
    return pin, folder


lv_pin, lv_source = source("source.json", "lvgl")
px_pin, px_source = source("pixman.json", "pixman")
suffix = a.target + ("-asan" if a.sanitize else "")
build = root / "output/soy" / ("lvgl-" + suffix)
px_build = root / "output/soy" / ("pixman-" + suffix)
build.mkdir(parents=True, exist_ok=True)
# A failed compile must not leave a stale executable looking like its result.
# Running device releases and their rollback copies are separate artifacts.
(build / "soy").unlink(missing_ok=True)
(build / "build-receipt.json").unlink(missing_ok=True)
env = os.environ.copy()
build_tools = a.build_tools.resolve() if a.build_tools else tool
if build_tools:
    env["PATH"] = str(build_tools) + os.pathsep + env.get("PATH", "")
    # Buildroot's relocated Meson launcher uses the running Python. Its module
    # directory is relative to the supplied host tool directory.
    modules = list(
        (build_tools.parent / "lib").glob("python*/site-packages/mesonbuild")
    )
    if modules:
        env["PYTHONPATH"] = (
            str(modules[0].parent) + os.pathsep + env.get("PYTHONPATH", "")
        )
meson = shutil.which("meson", path=env["PATH"])
ninja = shutil.which("ninja", path=env["PATH"])
if not meson or not ninja:
    p.error(
        "Meson and Ninja are required; provide --build-tools (Buildroot host/bin works)"
    )

px_cmd = [
    meson,
    "setup",
    str(px_build),
    str(px_source),
    "--buildtype=release",
    "--default-library=static",
    "-Dtests=disabled",
    "-Ddemos=disabled",
    "-Dgtk=disabled",
    "-Dlibpng=disabled",
]
if (px_build / "build.ninja").exists():
    px_cmd.append("--reconfigure")
arm_flags = (
    "-mcpu=cortex-a8 -mfpu=neon -mfloat-abi=hard -ffunction-sections -fdata-sections"
)
if a.target == "armv7":
    cross = build / "pixman-cross.ini"
    cross.write_text(
        "[binaries]\n"
        + "\n".join(
            f"{key} = {str(tool / value)!r}"
            for key, value in [
                ("c", "arm-linux-gcc"),
                ("ar", "arm-linux-ar"),
                ("strip", "arm-linux-strip"),
            ]
        )
        + "\n[host_machine]\nsystem = 'linux'\ncpu_family = 'arm'\ncpu = 'cortex-a8'\nendian = 'little'\n"
        + f"[built-in options]\nc_args = {arm_flags.split()!r}\n"
    )
    px_cmd += ["--cross-file", str(cross), "-Dneon=enabled"]
if a.sanitize:
    px_cmd += ["-Db_sanitize=address,undefined"]
cmd = [
    "cmake",
    "-S",
    str(root / "soy/lvgl"),
    "-B",
    str(build),
    f"-DLVGL_SOURCE={lv_source}",
    f"-DPIXMAN_SOURCE={px_source}",
    f"-DPIXMAN_BUILD={px_build}",
    "-DCMAKE_BUILD_TYPE=Release",
]
if a.target == "armv7":
    cmd += [
        "-DCMAKE_SYSTEM_NAME=Linux",
        "-DCMAKE_SYSTEM_PROCESSOR=arm",
        f"-DCMAKE_C_COMPILER={tool}/arm-linux-gcc",
        f"-DCMAKE_CXX_COMPILER={tool}/arm-linux-g++",
        f"-DCMAKE_C_FLAGS={arm_flags}",
        "-DCMAKE_EXE_LINKER_FLAGS=-static -Wl,--gc-sections",
    ]
if a.sanitize:
    cmd += [
        "-DCMAKE_C_FLAGS=-g -O1 -fsanitize=address,undefined -fno-omit-frame-pointer",
        "-DCMAKE_EXE_LINKER_FLAGS=-fsanitize=address,undefined",
    ]
with (build / "build.log").open("w") as log:
    for step in (
        px_cmd,
        [ninja, "-C", str(px_build), "-j2"],
        cmd,
        ["cmake", "--build", str(build), "-j2"],
    ):
        r = sp.run(step, stdout=log, stderr=sp.STDOUT, env=env)
        if r.returncode:
            raise SystemExit(f"Build failed; see {build}/build.log")
if a.target == "armv7":
    sp.run([str(tool / "arm-linux-strip"), str(build / "soy")], check=True)
receipt = {
    "source": lv_pin,
    "pixman": px_pin,
    "binary_sha256": digest(build / "soy"),
    "target": a.target,
    "sanitizers": a.sanitize,
    "project_sources": {
        path.relative_to(root).as_posix(): digest(path)
        for path in sorted(
            list((root / "soy/src").glob("*.[ch]"))
            + list((root / "soy/lvgl").glob("*"))
            + [Path(__file__).resolve()]
        )
        if path.is_file()
    },
    "meson": sp.check_output([meson, "--version"], env=env, text=True).strip(),
    "ninja": sp.check_output([ninja, "--version"], env=env, text=True).strip(),
}
(build / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(build / "soy")
