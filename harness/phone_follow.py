#!/usr/bin/env python3
"""Follow the running phone live, over USB or over Tailscale.

A user service (phone_watch.py install sets it up). Whenever the phone
answers, on USB (iphone4-usb) or over Tailscale (iphone4) when it is on Wi-Fi
somewhere else, this

- streams the kernel log as the kernel writes it,
- copies new lines of the service logs every 10 s (30 s over Tailscale, to
  spare the phone's battery), and
- collects Soy's journal the same way (soy/tools/scene.py journal pull), and
- keeps scenes the phone wrote itself in the scene library (scene.py adopt).

Everything lands in .runtime/phone/private/logs/YYYY-MM-DD/, so Claude and
Boris can watch it live and read it later. While the phone is out of reach
this tries again every 30 s; the phone keeps its kernel log (a 128 KiB ring)
and the files in /run until then. A reboot away from the laptop loses what
was not collected.

Usage: phone_follow.py run
"""
import argparse
import json
import os
from pathlib import Path
import subprocess as sp
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'soy/tools'))
import scene  # noqa: E402

PRIVATE = ROOT / '.runtime/phone/private'
LOGS = PRIVATE / 'logs'
STATE = LOGS / 'state.json'
# Soy's reading position and text size per scene; the boot pass restores it.
POSITIONS = PRIVATE / 'soy-positions'
FREQ = PRIVATE / 'time-freq-ppm'
USB_ADDRESS = '10.84.4.1'  # the laptop's end of the phone's USB network
# Service logs on the phone; keep.sh and the boot start the services this way.
FILES = {
    'keep.log': '/run/keep/keep.log',
    'soy.log': '/var/log/soy.log',
    'battery.log': '/run/n90-battery.log',
    'touch.log': '/run/n90-touch.log',
    'watchdog.log': '/run/n90-wdt.log',
}
# A reader left behind by a dropped link would keep its socket forever.
KMSG = ('for d in /proc/[0-9]*; do c=; read -r c < $d/comm 2>/dev/null; '
        '[ "$c" = cat ] && grep -q /dev/kmsg $d/cmdline 2>/dev/null && kill ${d#/proc/}; '
        'done; exec cat /dev/kmsg')


def append(name, text, when=None):
    folder = LOGS / time.strftime('%Y-%m-%d', time.localtime(when))
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(folder / name, 'a') as f:
        f.write(text)


def note(text):
    append('follow.log', time.strftime('%H:%M:%S ') + text + '\n')


class Link:
    """SSH over one route, through a keep-alive master of its own."""

    def __init__(self, host):
        sockets = os.environ.get('XDG_RUNTIME_DIR') or tempfile.gettempdir()
        self.args = ['ssh', '-F', str(PRIVATE / 'ssh_config'), '-o', 'BatchMode=yes',
                     '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=10',
                     '-o', 'ServerAliveCountMax=3', '-o', 'ControlMaster=auto',
                     '-o', f'ControlPath={sockets}/iphone4-follow-%C',
                     '-o', 'ControlPersist=60', host]

    def run(self, command, data=None, timeout=60):
        # A persisting master keeps stderr open: a pipe would never reach EOF.
        with tempfile.TemporaryFile() as err:
            try:
                result = sp.run(self.args + [command], input=data, stdout=sp.PIPE,
                                stderr=err, timeout=timeout)
            except sp.TimeoutExpired:
                raise scene.Unreachable(f'no answer within {timeout} s')
            err.seek(0)
            message = err.read().decode(errors='replace').strip()[-300:]
        if result.returncode == 255:
            raise scene.Unreachable(message or 'SSH failed')
        if result.returncode:
            raise scene.Failure(message or f'command failed ({result.returncode})')
        return result.stdout

    def stream(self, command):
        return sp.Popen(self.args + [command], stdout=sp.PIPE, stderr=sp.DEVNULL)


class Kernel(threading.Thread):
    """Copies /dev/kmsg records as they arrive, until the link drops."""

    def __init__(self, link, btime, state, lock):
        super().__init__(daemon=True)
        self.btime, self.state, self.lock = btime, state, lock
        self.proc = link.stream(KMSG)

    def run(self):
        for raw in self.proc.stdout:
            line = raw.decode(errors='replace').rstrip('\n')
            head, _, message = line.partition(';')
            try:
                seq, usec = (int(v) for v in head.split(',')[1:3])
            except ValueError:
                continue  # dictionary continuation lines start with a space
            with self.lock:
                if seq <= self.state['kmsg_seq']:
                    continue
                self.state['kmsg_seq'] = seq
            wall = self.btime + usec / 1e6
            stamp = time.strftime('%H:%M:%S', time.localtime(wall))
            append('kernel.log', f'{stamp}.{int(wall % 1 * 1000):03d} '
                   f'[{usec / 1e6:12.6f}] {message}\n', wall)

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
        self.join(5)


def copy_files(link, offsets):
    """Append the service logs' new whole lines; a partial last line waits."""
    script = []
    for name, path in FILES.items():
        o = offsets.get(name, 0)
        script.append(f's=$( (wc -c < {path}) 2>/dev/null || echo 0); o={o}; '
                      f'[ "$s" -lt "$o" ] && o=0; echo "@@ {name} $o $s"; '
                      f'[ "$s" -gt "$o" ] && tail -c +$((o + 1)) {path} | head -c $((s - o))')
    out = link.run('\n'.join(script) + '\ntrue', timeout=30)
    pos = 0
    while pos < len(out):
        end = out.index(b'\n', pos)
        _, name, o, s = out[pos:end].decode().split()
        body = out[end + 1:end + 1 + max(0, int(s) - int(o))]
        pos = end + 1 + len(body)
        whole = body[:body.rfind(b'\n') + 1]
        if whole:
            append(name, whole.decode(errors='replace'))
        offsets[name] = int(o) + len(whole)


def copy_positions(link):
    """Keep the latest copies of Soy's positions and the clock's learned
    frequency (kernel/n90-time) for the next boot."""
    out = link.run('cat /run/soy/positions 2>/dev/null; echo @@; '
                   'cat /run/time/freq_ppm 2>/dev/null; true', timeout=20)
    text, _, freq = out.partition(b'@@\n')
    for path, data in ((POSITIONS, text), (FREQ, freq.strip())):
        if data and (not path.exists() or path.read_bytes() != data):
            temp = path.with_suffix('.tmp')
            temp.write_bytes(data)
            temp.replace(path)


def adopt_scenes(link, state):
    """Keep scenes the phone wrote itself (kernel/n90-offline) in the library,
    so a reboot does not lose them."""
    current = link.run('readlink /opt/soy/current 2>/dev/null; true', timeout=20).decode().strip()
    if not current.startswith('releases/phone-') or state.get('adopted') == current:
        return
    library = scene.Library(PRIVATE / 'scenes').open()
    try:
        ids = scene.adopt(library, link)
    finally:
        library.lock.close()
    state['adopted'] = current
    if ids:
        note('kept scenes the phone wrote: ' + ', '.join(ids))


def on_usb():
    out = sp.run(['ip', '-o', '-4', 'addr', 'show'], capture_output=True, text=True).stdout
    return f' {USB_ADDRESS}/' in out


def session(route, host, interval):
    """Follow the phone over one route until the link drops."""
    link = Link(host)
    try:
        boot, btime = link.run('cat /proc/sys/kernel/random/boot_id; '
                               'sed -n "s/^btime //p" /proc/stat', timeout=20).decode().split()
    except scene.Failure:
        return False
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {}
    if state.get('boot_id') != boot:
        state = {'boot_id': boot, 'kmsg_seq': -1, 'files': {}}
        note(f'phone booted at {time.strftime("%H:%M:%S", time.localtime(int(btime)))} '
             f'(boot {boot[:8]})')
    note(f'following over {route}')
    lock = threading.Lock()
    kernel = Kernel(link, int(btime), state, lock)
    kernel.start()
    why = 'the kernel log stream ended'
    try:
        while kernel.is_alive():
            copy_files(link, state['files'])
            scene.journal_pull(link, scene.JOURNAL)
            copy_positions(link)
            adopt_scenes(link, state)
            with lock:
                save(state)
            if route == 'tailscale' and on_usb():
                why = 'the phone is back on USB'
                break
            kernel.join(interval)
    except scene.Failure as e:
        why = str(e)
    finally:
        kernel.stop()
        with lock:
            save(state)
    note(f'stopped following over {route}: {why}')
    return True


def save(state):
    temp = STATE.with_suffix('.tmp')
    temp.write_text(json.dumps(state) + '\n')
    temp.replace(STATE)


def run():
    LOGS.mkdir(mode=0o700, parents=True, exist_ok=True)
    while True:
        routes = [('usb', 'iphone4-usb', 10)] if on_usb() else []
        for route, host, interval in routes + [('tailscale', 'iphone4', 30)]:
            if session(route, host, interval):
                time.sleep(5)
                break
        else:
            time.sleep(30)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('command', choices=('run',))
    parser.parse_args()
    run()
