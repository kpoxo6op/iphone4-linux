#!/usr/bin/env python3
"""End-to-end check of scene.py and deploy.py against a simulated phone.

Runs in a private user and mount namespace where /opt, /run and /var/log are
empty tmpfs mounts. "SSH" runs each command in busybox ash with only busybox
applets on PATH, like the phone. A headless native renderer plays Soy: the
transport adds --headless when deploy.py starts it, because the simulated
phone has no display, and reports the simulated display as simpledrm.
Covers the boot install, hot publishing into the running
renderer, kept reading position, rejected scenes, show, focus after a reboot,
remove, undo, capture, offline saves and USB-to-Tailscale fallback.
Process and file checks only; no hardware claims.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess as sp
import sys
import time

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parents[1]
FAKE_SSH = '''#!/usr/bin/env python3
import os, subprocess, sys
host, command = sys.argv[-2], sys.argv[-1]
if host in os.environ.get('FAKE_DOWN', '').split(','):
    sys.exit(255)
command = command.replace('/opt/soy/current/soy --assets',
                          '/opt/soy/current/soy --headless --assets')
r = subprocess.run(['{busybox}', 'sh', '-c', command], env={{'PATH': '{applets}'}},
                   stdout=subprocess.PIPE)
sys.stdout.buffer.write(r.stdout.replace(b'"backend":"headless"', b'"backend":"simpledrm"'))
sys.exit(r.returncode)
'''


def outside(a):
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    result = sp.run(['unshare', '--user', '--map-root-user', '--mount', sys.executable,
                     __file__, '--native', str(a.native.resolve()), '--out', str(out),
                     '--inside'])
    if (out / 'result.json').exists():
        print((out / 'result.json').read_text().strip())
    return result.returncode or not (out / 'result.json').exists()


def inside(a):
    out = a.out
    for mount in ('/opt', '/run', '/var/log'):
        sp.run(['mount', '-t', 'tmpfs', 'none', mount], check=True)
    applets, bin_dir = out / 'busybox', out / 'bin'
    applets.mkdir()
    bin_dir.mkdir()
    busybox = shutil.which('busybox')
    sp.run([busybox, '--install', '-s', str(applets)], check=True)
    if not (applets / 'nohup').exists():  # The phone's busybox has it; Debian's lacks it.
        (applets / 'nohup').write_text(f"#!{busybox} sh\ntrap '' HUP\nexec \"$@\"\n")
        (applets / 'nohup').chmod(0o755)
    (bin_dir / 'ssh').write_text(FAKE_SSH.format(busybox=busybox, applets=applets))
    (bin_dir / 'ssh').chmod(0o755)
    os.environ['PATH'] = f'{bin_dir}:{os.environ["PATH"]}'
    library = out / 'library'
    checks = {}

    def scene(*args, down=''):
        env = {**os.environ, 'FAKE_DOWN': down}
        r = sp.run([sys.executable, str(TOOLS / 'scene.py'), '--library', str(library),
                    '--ssh-config', str(out / 'ssh_config'), '--binary', str(a.native),
                    *args], capture_output=True, text=True, env=env, timeout=120)
        with (out / 'scene.log').open('a') as log:
            log.write(f'$ scene.py {" ".join(args)} [down={down}] -> {r.returncode}\n'
                      f'{r.stdout}{r.stderr}\n')
        return r

    def status():
        return json.loads(Path('/run/soy/status.json').read_text())

    def wait(pred, seconds=8):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                s = status()
                if pred(s):
                    return s
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            time.sleep(0.05)
        raise AssertionError('state did not arrive')

    def control(text):
        with open('/run/soy/control', 'w') as f:
            f.write(text + '\n')

    def pid():
        return Path('/run/soy/renderer.pid').read_text().strip()

    def head():
        return sp.run(['git', '-C', str(library), 'rev-parse', 'HEAD'],
                      capture_output=True, text=True).stdout.strip()

    def manifest():
        return json.loads(Path('/opt/soy/current/manifest.json').read_text())

    note = out / 'note.md'
    note.write_text('# Overnight\n\nThe *phone* shows this **note**.\n\n- one\n- two\n')
    try:
        r = scene('sync')
        checks['boot_installs_library'] = (
            r.returncode == 0 and 'Installed the renderer' in r.stdout and
            wait(lambda s: s['scene'] == 'reader')['count'] == 5 and
            manifest().get('scenes_revision') == head())
        renderer = pid()
        r = scene('list')
        checks['list_reports_in_sync'] = r.returncode == 0 and 'matches the library' in r.stdout
        control('goto reader')
        control('scroll 900')
        wait(lambda s: s['scene'] == 'reader' and s['scroll'] == 900)
        before = manifest()
        r = scene('put', str(note), '--label', 'Overnight', '--accent', 'cyan', '--show',
                  '-m', 'check')
        s = wait(lambda s: s['scene'] == 'note')
        checks['hot_publish_shows_scene'] = (
            r.returncode == 0 and 'Published 6 scenes' in r.stdout and pid() == renderer and
            s['scenes'][-1] == 'note' and s['bundle_loads'] == 2)
        checks['manifest_and_previous'] = (
            manifest()['scenes_revision'] == head() and
            manifest()['binary_sha256'] == before['binary_sha256'] and
            os.readlink('/opt/soy/previous') != os.readlink('/opt/soy/current'))
        control('goto reader')
        checks['reading_position_kept'] = wait(
            lambda s: s['scene'] == 'reader')['scroll'] == 900
        commit = head()
        bad = out / 'bad.md'
        bad.write_text('---\nid: bad\ntitle: Nope\n---\nx\n')
        r = scene('put', str(bad))
        checks['bad_scene_rejected_locally'] = (
            r.returncode == 1 and "unknown frontmatter key 'title'" in r.stderr and
            head() == commit and not (library / 'bad.md').exists() and
            'bad' not in (library / 'index').read_text() and status()['bundle_loads'] == 2)
        r = scene('remove', 'note')
        checks['remove'] = r.returncode == 0 and wait(lambda s: s['count'] == 5) and \
            'note' not in status()['scenes']
        r = scene('undo')
        checks['undo'] = r.returncode == 0 and wait(lambda s: s['count'] == 6) and \
            status()['scenes'][-1] == 'note'
        r = scene('capture', '--out', str(out / 'phone.png'))
        png = (out / 'phone.png').read_bytes() if (out / 'phone.png').exists() else b''
        checks['capture_png'] = r.returncode == 0 and png[:8] == b'\x89PNG\r\n\x1a\n'
        r = scene('preview', 'note', '--out', str(out / 'preview.png'))
        checks['preview_png'] = (r.returncode == 0 and
                                 (out / 'preview.png').read_bytes()[:4] == b'\x89PNG')
        note.write_text('---\nid: note\nlabel: Overnight\naccent: cyan\n---\n# Changed\n')
        r = scene('put', str(note), down='iphone4-usb,iphone4')
        checks['offline_put_saved'] = (r.returncode == 3 and head() != commit and
                                       'next boot' in r.stdout)
        r = scene('sync', down='iphone4-usb')
        checks['tailscale_fallback_publishes'] = (
            r.returncode == 0 and 'over Tailscale' in r.stdout and
            manifest()['scenes_revision'] == head())
        checks['sync_recorded_for_watcher'] = (
            (library / '.git/soy-synced').read_text().strip() == head())
        r = scene('show', 'note')
        checks['show'] = r.returncode == 0 and wait(lambda s: s['scene'] == 'note') and \
            (library / '.git/soy-focus').read_text().strip() == 'note'
        sp.run(['kill', pid()])  # A reboot empties /opt/soy and /run/soy.
        time.sleep(0.5)
        for path in ('/opt/soy', '/run/soy'):
            shutil.rmtree(path)
        r = scene('sync')
        checks['reboot_opens_focus'] = (
            r.returncode == 0 and wait(lambda s: s['scene'] == 'note')['count'] == 6)
        control('quit')
        time.sleep(0.5)
    except Exception as exc:  # Record the failure with the evidence.
        checks['completed'] = False
        checks['error'] = f'{type(exc).__name__}: {exc}'
    result = {'passed': bool(checks) and all(v is True for v in checks.values()),
              'checks': checks,
              'scope': 'Simulated phone: busybox ash, headless native renderer; '
                       'no hardware claims'}
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    if Path('/var/log/soy.log').exists():
        shutil.copyfile('/var/log/soy.log', out / 'renderer.log')
    try:
        os.kill(int(pid()), 15)
    except (OSError, ValueError):
        pass
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--native', type=Path, default=ROOT / 'output/soy/lvgl-native/soy')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    args = p.parse_args()
    raise SystemExit(inside(args) if args.inside else outside(args))
