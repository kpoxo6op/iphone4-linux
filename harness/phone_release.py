#!/usr/bin/env python3
"""Build, sign and publish the phone's software as an over-the-air release.

The phone pulls releases itself (kernel/n90-ota): it checks the repository's
latest GitHub release, verifies the manifest's Ed25519 signature and every
file's SHA-256, installs, and rolls back if it is not healthy a minute later.

  phone_release.py keygen    once: the signing key in .runtime/phone/private/ota,
                             its public half in kernel/n90-ota/ota.pub
  phone_release.py build     output/release: phone-release.tar, .manifest, .sig
  phone_release.py publish   build, then create a GitHub release from HEAD

A release holds the renderer and its fonts and the phone's own tools, built
from this checkout's outputs (make the kernel/n90-* directories and
soy/tools/build_touch.py first). It never holds Apple firmware, kernel
modules, Wi-Fi keys, scenes or the story model.
"""
import argparse
import hashlib
import io
from pathlib import Path
import subprocess as sp
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
KEYDIR = ROOT / '.runtime/phone/private/ota'
SECRET = KEYDIR / 'signing.key'
PUBLIC = ROOT / 'kernel/n90-ota/ota.pub'
SIG = ROOT / 'output/ota/n90-sig-host'
OUT = ROOT / 'output/release'

# Path in the release: (source, mode). The phone installs sbin/ to /usr/sbin,
# etc/ to /etc and opt/ to /opt; soy/ becomes a renderer release.
FILES = {
    'soy/soy': ('output/soy/lvgl-armv7/soy', 0o700),
    'sbin/n90-keep': ('kernel/n90-keep/keep.sh', 0o755),
    'sbin/n90-wifi-keep': ('kernel/n90-wifi/wifi-keep.sh', 0o755),
    'sbin/n90-firewall': ('kernel/n90-net/firewall.sh', 0o755),
    'sbin/n90-scene': ('kernel/n90-offline/scene.sh', 0o755),
    'sbin/n90-story': ('kernel/n90-offline/story.sh', 0o755),
    'sbin/n90-battery': ('output/battery/n90-battery', 0o755),
    'sbin/n90-time': ('output/time/n90-time', 0o755),
    'sbin/n90-ota': ('kernel/n90-ota/ota.sh', 0o755),
    'sbin/n90-sig': ('output/ota/n90-sig', 0o755),
    'opt/n90-ota/wget': ('output/ota/wget', 0o755),
    'etc/n90/firewall.nft': ('kernel/n90-net/firewall.nft', 0o644),
    'etc/n90/ota.pub': ('kernel/n90-ota/ota.pub', 0o644),
}


def git(*args):
    return sp.check_output(['git', '-C', str(ROOT), *args], text=True).strip()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def keygen():
    if SECRET.exists():
        raise SystemExit(f'{SECRET} exists; a new key would orphan phones that trust the old one')
    KEYDIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    sp.run([str(SIG), 'keygen', str(SECRET), str(PUBLIC)], check=True)
    print(f'secret {SECRET}\npublic {PUBLIC}: {PUBLIC.read_text().strip()}')


def build():
    if git('status', '--porcelain', '--untracked-files=no'):
        raise SystemExit('the checkout has uncommitted changes; a release names one commit')
    commit = git('rev-parse', 'HEAD')
    committed = int(git('log', '-1', '--format=%ct'))
    version = time.strftime('%Y-%m-%d', time.gmtime(committed)) + '-' + commit[:7]
    files = {}
    for name, (source, mode) in FILES.items():
        path = ROOT / source
        if not path.is_file():
            raise SystemExit(f'missing {source}')
        files[name] = (path.read_bytes(), mode)
    for font in sorted((ROOT / 'soy/assets').iterdir()):
        if font.is_file() and not font.name.startswith('.'):
            files[f'soy/assets/{font.name}'] = (font.read_bytes(), 0o644)
    blob = io.BytesIO()
    with tarfile.open(fileobj=blob, mode='w', format=tarfile.USTAR_FORMAT) as tar:
        for name, (data, mode) in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), mode, committed
            tar.addfile(info, io.BytesIO(data))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'phone-release.tar').write_bytes(blob.getvalue())
    lines = [f'version {version}', f'commit {commit}', f'committed {committed}',
             f'tar {sha(blob.getvalue())}']
    lines += [f'file {name} {sha(data)} {mode:o}' for name, (data, mode) in files.items()]
    manifest = OUT / 'phone-release.manifest'
    manifest.write_text('\n'.join(lines) + '\n')
    sp.run([str(SIG), 'sign', str(SECRET), str(manifest)], check=True)
    sp.run([str(SIG), 'verify', str(PUBLIC), str(manifest)], check=True)
    print(f'{version}: {len(files)} files, {len(blob.getvalue()) // 1024} KiB, signed')
    return version, commit


def publish():
    version, commit = build()
    tag = f'phone-{version}'
    notes = (f'The phone\'s own software at {commit[:7]}: the Soy renderer and fonts and the '
             'n90 tools. Phones running n90-ota install it by themselves after checking its '
             'Ed25519 signature (kernel/n90-ota/README.md).')
    sp.run(['gh', 'release', 'create', tag, '--repo', 'kpoxo6op/iphone4-linux', '--target',
            commit, '--title', f'Phone {version}', '--notes', notes, '--latest',
            *[str(OUT / name) for name in ('phone-release.manifest',
                                           'phone-release.manifest.sig', 'phone-release.tar')]],
           check=True)
    print(f'published {tag}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('command', choices=('keygen', 'build', 'publish'))
    parser.add_argument('--key', type=Path, help=f'signing key (default {SECRET})')
    a = parser.parse_args()
    if a.key:
        SECRET = a.key
    {'keygen': keygen, 'build': build, 'publish': publish}[a.command]()
