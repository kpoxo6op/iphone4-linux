#!/usr/bin/env python3
"""Put Markdown scenes on the phone: the way AI (or anyone) draws Soy.

The scene library is a private Git repository on this host, by default
.runtime/phone/private/scenes: an ordered `index` plus one Markdown file per
scene. It is the source of truth. Every change is checked with the native
renderer, committed, then published to the phone while the renderer keeps
running: a new release that hard-links the running binary and assets, a
hash and renderer check on the phone, an atomic switch that keeps the previous
release, and a reload. The reader's place survives. If the phone is out of
reach the change stays committed, and the next publish or boot brings it over.

    scene.py put note.md --show    add or replace a scene and bring it up
    scene.py remove note           take a scene off the phone
    scene.py show note             bring a scene up (also after a reboot)
    scene.py list                  library, history and what the phone shows
    scene.py undo                  return to the previous published scenes
    scene.py publish               publish hand edits made in the library
    scene.py preview note --out x.png   render locally at 640 x 960
    scene.py capture --out x.png   save what the phone is showing
    scene.py sync                  make the phone match the library (boot)
    scene.py journal               what was read on the phone today, and the battery
    scene.py journal pull          copy the phone's journal here (the watcher does it)

docs/soy/scenes.md describes the scene format and the design rules.
"""
import argparse
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess as sp
import sys
import tarfile
import tempfile
import time
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / '.runtime/phone/private'
NATIVE = ROOT / 'output/soy/lvgl-native/soy'
ARM = ROOT / 'output/soy/lvgl-armv7/soy'
ASSETS = ROOT / 'soy/assets'
DEFAULT_SCENES = ROOT / 'soy/scenes'
HOSTS = ('iphone4-usb', 'iphone4')  # USB first, then Tailscale
SCENE_ID = re.compile(r'[A-Za-z0-9_-]{1,40}')
RELEASE = re.compile(r'releases/[A-Za-z0-9-]+')
AUTHOR = ['-c', 'user.name=Soy scenes', '-c', 'user.email=soy@iphone4.invalid']
FRAME_BYTES = 640 * 960 * 3 + 15


class Failure(Exception):
    pass


class Unreachable(Failure):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def scene_ids(index_text):
    return [line.strip() for line in index_text.splitlines()
            if line.strip() and not line.startswith('#')]


class Library:
    def __init__(self, path):
        self.path = path

    def git(self, *args, data=None):
        result = sp.run(['git', '-C', str(self.path), *AUTHOR, *args],
                        input=data, capture_output=True)
        if result.returncode:
            raise Failure(f'git {args[0]}: {result.stderr.decode().strip()}')
        return result.stdout

    def open(self):
        """Create the library from the default bundle on first use, and lock it."""
        if not (self.path / '.git').is_dir():
            if self.path.exists() and any(self.path.iterdir()):
                raise Failure(f'{self.path} exists but is not a scene library')
            self.path.mkdir(mode=0o700, parents=True, exist_ok=True)
            for name in ['index'] + [i + '.md' for i in
                                     scene_ids((DEFAULT_SCENES / 'index').read_text())]:
                shutil.copyfile(DEFAULT_SCENES / name, self.path / name)
            self.git('init', '-q', '-b', 'main')
            self.git('add', '-A')
            self.git('commit', '-q', '-m', 'Start from the default scenes')
        self.lock = open(self.path / '.git/soy-scene.lock', 'w')
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        return self

    def index(self):
        index = self.path / 'index'
        return scene_ids(index.read_text()) if index.exists() else []

    def write_index(self, ids):
        (self.path / 'index').write_text(''.join(i + '\n' for i in ids))

    def head(self):
        return self.git('rev-parse', 'HEAD').decode().strip()

    def commit(self, message):
        self.git('add', '-A')
        if not self.git('status', '--porcelain').strip():
            return False
        self.git('commit', '-q', '-m', message)
        return True

    def files(self, rev='HEAD'):
        """The committed bundle: the index and each listed scene, nothing else."""
        index = self.git('show', f'{rev}:index')
        names = ['index'] + [i + '.md' for i in scene_ids(index.decode())]
        archive = self.git('archive', '--format=tar', rev, '--', *names)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            return {m.name: tar.extractfile(m).read() for m in tar if m.isfile()}

    @property
    def focus_file(self):
        return self.path / '.git/soy-focus'

    def focus(self):
        try:
            return self.focus_file.read_text().strip()
        except FileNotFoundError:
            return ''


def check(directory, scene=None):
    """Validate a bundle with the same renderer code the phone runs."""
    if not NATIVE.exists():
        raise Failure(f'No native renderer at {NATIVE}. Build it with: '
                      'python3 soy/tools/build_touch.py --target native')
    args = [str(NATIVE), '--check', '--assets', str(ASSETS), '--scenes', str(directory)]
    if scene:
        args += ['--scene', scene]
    result = sp.run(args, capture_output=True, text=True, timeout=60)
    if result.returncode:
        lines = [line.removeprefix('Invalid scene bundle: ')
                 for line in result.stderr.splitlines() if line.strip()]
        raise Failure(lines[0] if lines else 'Invalid scene bundle')


def start_scene(ids, focus):
    return focus if focus in ids else 'reader' if 'reader' in ids else ids[0]


class Phone:
    def __init__(self, ssh_config, host=None, binary=ARM):
        self.config = ssh_config
        self.binary = binary
        self.hosts = [host] if host else list(HOSTS)
        self.host = None
        sockets = os.environ.get('XDG_RUNTIME_DIR') or tempfile.gettempdir()
        self.control = f'{sockets}/soy-ssh-%C'

    def _ssh(self, host, command, data, timeout):
        args = ['ssh', '-F', str(self.config), '-o', 'BatchMode=yes',
                '-o', 'ConnectTimeout=6', '-o', 'ControlMaster=auto',
                '-o', f'ControlPath={self.control}', '-o', 'ControlPersist=30',
                host, command]
        # A persisting master keeps stderr open: a pipe would never reach EOF.
        with tempfile.TemporaryFile() as err:
            try:
                result = sp.run(args, input=data, stdout=sp.PIPE, stderr=err,
                                timeout=timeout)
            except sp.TimeoutExpired:
                raise Unreachable(f'No answer from {host} within {timeout} s')
            err.seek(0)
            result.stderr = err.read()
        return result

    def run(self, command, data=None, timeout=60):
        """Run a shell command on the phone. The first command picks the link,
        so it must be safe to repeat."""
        for host in [self.host] if self.host else self.hosts:
            result = self._ssh(host, command, data, timeout)
            if result.returncode != 255:
                self.host = host
                break
        else:
            raise Unreachable('The phone is not reachable over ' +
                              ' or '.join([self.host] if self.host else self.hosts))
        if result.returncode:
            raise Failure(result.stderr.decode(errors='replace').strip()[-800:] or
                          f'Phone command failed ({result.returncode})')
        return result.stdout

    def state(self):
        out = self.run(r'''cur=$(readlink /opt/soy/current 2>/dev/null)
p=$(cat /run/soy/renderer.pid 2>/dev/null); run=no
case "$p" in ''|*[!0-9]*) ;; *) if kill -0 "$p" 2>/dev/null; then
 case "$(readlink /proc/$p/exe)" in /opt/soy/releases/*/soy) run=yes;; esac; fi;; esac
echo "$cur"; echo "$run"
cat /run/soy/status.json 2>/dev/null; echo; echo @@
[ -n "$cur" ] && cat /opt/soy/current/manifest.json 2>/dev/null; true''').decode()
        current, running, rest = out.split('\n', 2)
        status, _, manifest = rest.partition('\n@@\n')
        state = {'current': current, 'running': running == 'yes'}
        for key, text in (('status', status), ('manifest', manifest)):
            try:
                state[key] = json.loads(text)
            except json.JSONDecodeError:
                state[key] = {}
        if current and not RELEASE.fullmatch(current):
            raise Failure(f'Unexpected release path on the phone: {current}')
        return state

    def status(self):
        try:
            return json.loads(self.run('cat /run/soy/status.json'))
        except (Failure, json.JSONDecodeError):
            return {}

    def command(self, text):
        """Write to the renderer's control FIFO without blocking if it is gone."""
        self.run('[ -p /run/soy/control ] || { echo "The renderer is not running" >&2; '
                 f"exit 1; }}; printf '%s\\n' '{text}' 1<>/run/soy/control")


def in_sync(state, files):
    if not state['running']:
        return False
    published = {k[len('scenes/'):]: v for k, v in state['manifest'].get('files', {}).items()
                 if k.startswith('scenes/')}
    return published == {name: sha(data) for name, data in files.items()}


def hot_publish(phone, state, files, revision, focus):
    """Publish scenes into the running renderer. Returns the new release name."""
    manifest = dict(state['manifest'])
    kept = {k: v for k, v in manifest['files'].items() if not k.startswith('scenes/')}
    manifest['files'] = {**kept, **{'scenes/' + n: sha(d) for n, d in files.items()}}
    manifest['scenes_revision'] = revision
    manifest_bytes = (json.dumps(manifest, indent=2) + '\n').encode()
    release = (('prototype-' if manifest.get('uncommitted_soy') else
                manifest['git_revision'][:12] + '-') + sha(manifest_bytes)[:12])
    sums = {'soy': manifest['binary_sha256'], **manifest['files'],
            'manifest.json': sha(manifest_bytes)}
    payload = {**{'scenes/' + n: d for n, d in files.items()},
               'manifest.json': manifest_bytes,
               'SHA256SUMS': ''.join(f'{h}  {n}\n' for n, h in sums.items()).encode()}
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w', format=tarfile.USTAR_FORMAT) as tar:
        for name, data in payload.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o600
            tar.addfile(info, io.BytesIO(data))
    before = state['status']
    stage = 'releases/.incoming-' + uuid.uuid4().hex
    phone.run(f'''set -e
umask 077
cd /opt/soy
cur=$(readlink current)
[ "$cur" = "{state['current']}" ] || {{ echo "The phone's release changed meanwhile; try again" >&2; exit 3; }}
trap 'rm -rf "/opt/soy/{stage}"' EXIT
mkdir {stage}
tar -xf - -C {stage}
ln "$cur/soy" {stage}/soy
mkdir {stage}/assets
for f in "$cur"/assets/*; do ln "$f" {stage}/assets/; done
cd {stage}
sha256sum -c SHA256SUMS >/dev/null
./soy --check --assets assets --scenes scenes --scene {focus} >/dev/null
cd /opt/soy
if [ -e releases/{release} ]; then
 (cd releases/{release} && sha256sum -c /opt/soy/{stage}/SHA256SUMS >/dev/null)
else
 mv {stage} releases/{release}
fi
if [ "$cur" != releases/{release} ]; then
 rm -f current.new; ln -s releases/{release} current.new; mv -Tf current.new current
 rm -f previous.new; ln -s "$cur" previous.new; mv -Tf previous.new previous
fi
p=$(cat /run/soy/renderer.pid)
case "$(readlink /proc/$p/exe)" in /opt/soy/releases/*/soy) ;; *)
 echo "Unexpected renderer owner" >&2; exit 4;; esac
kill -HUP "$p"''', buf.getvalue())
    if 'bundle_loads' not in before:
        time.sleep(1)  # An older renderer cannot confirm a reload.
        return release
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        now = phone.status()
        if now.get('bundle_loads', 0) > before['bundle_loads']:
            return release
        if now.get('bundle_failures', 0) > before['bundle_failures']:
            phone.run(f'''cd /opt/soy
[ "$(readlink current)" = releases/{release} ] || exit 0
rm -f current.rollback; ln -s {state['current']} current.rollback
mv -Tf current.rollback current
kill -HUP "$(cat /run/soy/renderer.pid)"''')
            raise Failure('The phone rejected the scenes and kept the previous ones: ' +
                          now.get('bundle_error', 'unknown error'))
        time.sleep(0.2)
    raise Failure('The renderer did not confirm the reload within 15 s')


def full_deploy(phone, files, revision, focus, receipt):
    """No running renderer: install the ARM build with these scenes."""
    if not phone.binary.exists():
        raise Failure(f'The renderer is not running and there is no build at {phone.binary}')
    with tempfile.TemporaryDirectory() as tmp:
        scenes = Path(tmp) / 'scenes'
        scenes.mkdir()
        for name, data in files.items():
            (scenes / name).write_bytes(data)
        receipt = receipt or Path(tmp) / 'receipt.json'
        result = sp.run([sys.executable, str(ROOT / 'soy/tools/deploy.py'),
                         '--ssh-config', str(phone.config), '--host', phone.host,
                         '--binary', str(phone.binary), '--scenes', str(scenes),
                         '--scenes-revision', revision, '--scene', focus,
                         '--receipt', str(receipt)],
                        capture_output=True, text=True, timeout=300)
        try:
            record = json.loads(receipt.read_text())
        except (OSError, ValueError):
            record = {}
    if result.returncode:
        raise Failure('Installing the renderer failed: ' + (
            record.get('error') or (result.stdout + result.stderr).strip()[-600:]))
    return record['release']


def adopt(library, phone):
    """Copy scenes the phone wrote itself into the library; return their IDs.

    Programs on the phone publish with n90-scene (kernel/n90-offline), for
    example while it has no connection. Their scenes say `source: phone` and
    live in a release named phone-*. Keeping them in the library first means
    a later publish or a reboot does not drop them.
    """
    out = phone.run('readlink /opt/soy/current; cat /opt/soy/current/manifest.json').decode()
    current, _, manifest = out.partition('\n')
    if not current.startswith('releases/phone-'):
        return []
    try:
        published = json.loads(manifest).get('files', {})
    except ValueError:
        return []
    files = library.files()
    ids = library.index()
    adopted = []
    for name, digest in published.items():
        scene_id = name.removeprefix('scenes/').removesuffix('.md')
        if (not name.startswith('scenes/') or not name.endswith('.md') or
                not SCENE_ID.fullmatch(scene_id) or
                sha(files.get(scene_id + '.md', b'')) == digest):
            continue
        text = phone.run(f'cat /opt/soy/current/scenes/{scene_id}.md')
        head = text.decode(errors='replace').split('\n---\n', 1)[0].splitlines()
        if sha(text) != digest or not any(
                line.startswith('source:') and line[7:].strip().startswith('phone')
                for line in head):
            continue
        (library.path / f'{scene_id}.md').write_bytes(text)
        if scene_id not in ids:
            ids.append(scene_id)
        adopted.append(scene_id)
    if adopted:
        library.write_index(ids)
        try:
            check(library.path)
        except Failure:
            library.git('checkout', '--', '.')
            library.git('clean', '-fq', '--', *[i + '.md' for i in adopted])
            raise
        library.commit('Written on the phone: ' + ', '.join(adopted))
    return adopted


def sync(library, phone, receipt=None, show=None, import_phone=True):
    """Make the phone show the library's committed scenes. Returns a summary."""
    try:
        if import_phone:
            adopt(library, phone)
    except Unreachable:
        raise
    except Failure:
        pass  # a phone scene that fails the check here is not kept
    files = library.files()
    ids = scene_ids(files['index'].decode())
    focus = start_scene(ids, library.focus())
    state = phone.state()
    via = {'iphone4-usb': 'USB', 'iphone4': 'Tailscale'}.get(phone.host, phone.host)
    if in_sync(state, files):
        summary = f'The phone already shows these scenes (over {via}).'
    elif state['running'] and state['manifest'].get('files'):
        release = hot_publish(phone, state, files, library.head(), focus)
        summary = f'Published {len(ids)} scenes to the phone over {via} ({release}).'
    else:
        release = full_deploy(phone, files, library.head(), focus, receipt)
        summary = f'Installed the renderer with {len(ids)} scenes over {via} ({release}).'
    # The watcher compares this with the library to catch up a phone that
    # was away when scenes were published.
    (library.path / '.git/soy-synced').write_text(library.head() + '\n')
    if show:
        phone.command('goto ' + show)
        deadline = time.monotonic() + 5
        while phone.status().get('scene') != show:
            if time.monotonic() > deadline:
                raise Failure(f'The phone did not switch to {show}')
            time.sleep(0.2)
        summary += f' Showing {show}.'
    return summary


def read_scene(source, scene_id, label, accent):
    """Return (id, text) for a Markdown file, adding frontmatter if it has none."""
    text = (sys.stdin.read() if source == '-' else Path(source).read_text(encoding='utf-8'))
    text = text.lstrip('﻿').replace('\r\n', '\n').replace('\r', '\n')
    if not text.endswith('\n'):
        text += '\n'
    if text.startswith('---\n'):
        if scene_id or label or accent:
            raise Failure('The file has frontmatter; set id, label and accent there')
        head = text[4:].split('\n---\n', 1)[0]
        found = [line.split(':', 1)[1].strip() for line in head.split('\n')
                 if line.startswith('id:')]
        if not found:
            raise Failure("The frontmatter has no 'id:' line")
        if not SCENE_ID.fullmatch(found[0]):
            raise Failure(f"'{found[0]}' is not a scene ID (A-Z a-z 0-9 - _, at most 40)")
        return found[0], text
    scene_id = scene_id or ('' if source == '-' else Path(source).stem)
    if not SCENE_ID.fullmatch(scene_id):
        raise Failure(f"'{scene_id}' is not a scene ID (A-Z a-z 0-9 - _, at most 40); "
                      'pass --id')
    head = f'---\nid: {scene_id}\nlabel: {label or scene_id}\n'
    head += f'accent: {accent}\n' if accent else ''
    return scene_id, head + '---\n' + text


def ppm_to_png(ppm, out):
    match = re.match(rb'P6\s+(\d+)\s+(\d+)\s+255\s', ppm)
    if not match:
        raise Failure('Not a P6 image')
    w, h = int(match[1]), int(match[2])
    data = ppm[match.end():]
    rows = b''.join(b'\0' + data[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(kind, body):
        return (struct.pack('>I', len(body)) + kind + body +
                struct.pack('>I', zlib.crc32(kind + body)))
    out.write_bytes(b'\x89PNG\r\n\x1a\n' +
                    chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) +
                    chunk(b'IDAT', zlib.compress(rows, 6)) + chunk(b'IEND', b''))


def change(library, phone, message, edit, show=None, import_phone=True):
    """Apply an edit to the library, check, commit and publish it."""
    saved = {p: p.read_bytes() for p in library.path.iterdir() if p.is_file()}
    edit()
    try:
        check(library.path)
    except Failure:
        for p in library.path.iterdir():
            if p.is_file() and p not in saved:
                p.unlink()
        for p, data in saved.items():
            p.write_bytes(data)
        raise
    if show:
        library.focus_file.write_text(show + '\n')
    committed = library.commit(message)
    revision = library.head()[:7]
    print(f'Saved in the scene library ({revision}).' if committed else
          'The library already had these scenes.')
    return publish(library, phone, show, import_phone=import_phone)


def publish(library, phone, show=None, import_phone=True):
    try:
        print(sync(library, phone, show=show, import_phone=import_phone))
        return 0
    except Unreachable as exc:
        print(f'{exc}. The phone will get these scenes on its next boot or publish.')
        return 3


JOURNAL = PRIVATE / 'journal'
VIEWPORT = 748  # Soy's reading area, BOTTOM - TOP


def _journal_pull_one(phone, directory, remote="/run/soy/journal.jsonl", state_name="state.json"):
    """Append one bounded producer; each has its own per-boot cursor."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    state_file = directory / state_name
    try:
        state = json.loads(state_file.read_text())
    except (OSError, ValueError):
        state = {}
    boot, size = phone.run('cat /proc/sys/kernel/random/boot_id; '
                           f'if [ -f {remote} ]; then wc -c < {remote}; else echo 0; fi'
                           ).decode().split()[:2]
    size = int(size)
    offset = state.get('offset', 0) if state.get('boot_id') == boot else 0
    if size < offset:  # rotated at 1 MiB; the rotated tail is not fetched
        offset = 0
    if size == offset:
        return 0
    data = phone.run(f'tail -c +{offset + 1} {remote}')
    whole = data[:data.rfind(b'\n') + 1]  # a partial last line waits
    days = {}
    for line in whole.decode(errors='replace').splitlines():
        try:
            event = json.loads(line)
            day = time.strftime('%Y-%m-%d', time.localtime(float(event['t'])))
        except (ValueError, KeyError, TypeError):
            continue
        event['boot'] = boot[:8]
        days.setdefault(day, []).append(json.dumps(event, separators=(',', ':')))
    for day, lines in days.items():
        with open(directory / f'{day}.jsonl', 'a') as f:
            f.write(''.join(line + '\n' for line in lines))
    state_file.write_text(json.dumps({'boot_id': boot, 'offset': offset + len(whole)}) + '\n')
    return sum(len(lines) for lines in days.values())


def journal_pull(phone, directory):
    """Collect UI and sense evidence, including the offline trip after return."""
    return (_journal_pull_one(phone, directory) +
            _journal_pull_one(phone, directory, '/run/sense/journal.jsonl', 'sense-state.json'))


def minutes(seconds):
    if seconds < 60:
        return 'under a minute'
    m = round(seconds / 60)
    return f'{m} min' if m < 60 else f'{m // 60} h {m % 60:02d} min'


def journal_summary(directory, day, labels):
    """Plain-language account of one day: reading time, how far, battery."""
    events = []
    try:
        for line in (directory / f'{day}.jsonl').read_text().splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
    except OSError:
        pass
    if not events:
        return f'No journal for {day}.'
    events.sort(key=lambda e: e['t'])
    reading, furthest, wakes, sleeps, restarts, battery, oopses = {}, {}, {}, {}, {}, [], []
    shutdowns, stops, firewall, updates = [], [], [], []
    scene, awake, since, last = None, False, None, None

    def add(name, seconds):
        if name:
            reading[name] = reading.get(name, 0) + max(0, min(seconds, 3600))

    def read_to(name, scroll, height):
        if name and height:
            furthest[name] = max(furthest.get(name, 0), min(1, (scroll + VIEWPORT) / height))

    for e in events:
        t, kind = float(e['t']), e.get('e')
        if kind == 'start':
            # A renderer that crashed left its last stretch open: count a minute.
            if awake and last is not None:
                add(scene, min(t, last + 60) - since)
            scene, awake, since = e.get('scene'), True, t
        elif kind == 'scene':
            if awake:
                add(scene, t - since)
            read_to(e.get('left'), e.get('scroll', 0), e.get('height', 0))
            scene, since = e.get('scene'), t
        elif kind == 'sleep':
            if awake:
                add(scene, t - since)
            read_to(e.get('scene'), e.get('scroll', 0), e.get('height', 0))
            awake = False
            sleeps[e.get('why')] = sleeps.get(e.get('why'), 0) + 1
        elif kind == 'wake':
            awake, since = True, t
            wakes[e.get('why')] = wakes.get(e.get('why'), 0) + 1
        elif kind == 'battery':
            battery.append(e)
        elif kind == 'restart':
            restarts[e.get('what')] = restarts.get(e.get('what'), 0) + 1
        elif kind == 'oops':
            oopses.append(t)
        elif kind == 'shutdown':
            shutdowns.append(e)
        elif kind == 'last_stop':
            stops.append(e)
        elif kind == 'firewall':
            firewall.append(e)
        elif kind in ('ota', 'charge'):
            updates.append(e)
        last = t
    if awake:
        end = min(time.time(), last + 60) if day == time.strftime('%Y-%m-%d') else last
        add(scene, end - since)

    clock = lambda t: time.strftime('%H:%M', time.localtime(float(t)))
    out = [f"{time.strftime('%a %d %b %Y', time.strptime(day, '%Y-%m-%d'))}, "
           f"{clock(events[0]['t'])}-{clock(events[-1]['t'])}"]
    total = sum(reading.values())
    out.append(f'Screen on: {minutes(total)}')
    for name, seconds in sorted(reading.items(), key=lambda kv: -kv[1]):
        how_far = f', read to {round(furthest[name] * 100)}%' if name in furthest else ''
        out.append(f'  {labels.get(name, name)}: {minutes(seconds)}{how_far}')
    if battery:
        def describe(b):
            text = {'Discharging': 'on battery'}.get(b.get('state'), (b.get('state') or '').lower())
            volts = f"{b['mv'] / 1000:.2f} V" if b.get('mv', -1) > 0 else 'no voltage'
            percent = f" (~{b['percent']}%)" if b.get('percent', -1) >= 0 else ''
            return f"{text} {volts}{percent} at {clock(b['t'])}"
        out.append(f'Battery: {describe(battery[0])}; then {describe(battery[-1])}')
    def times(counts):
        n = sum(counts.values())
        how = 'once' if n == 1 else 'twice' if n == 2 else f'{n} times'
        return f"{how} ({', '.join(f'{k} {v}' for k, v in counts.items())})"
    if wakes or sleeps:
        out.append(f'Screen woke {times(wakes)}, slept {times(sleeps)}' if wakes else
                   f'Screen slept {times(sleeps)}')
    out.append('Restarted by keep: ' + (times(restarts) if restarts else 'nothing'))
    if firewall:
        out.append(f"Firewall: {firewall[-1].get('state')} since {clock(firewall[-1]['t'])}")
    for e in updates:
        if e.get('e') == 'ota':
            out.append(f"Update {e.get('version')}: {e.get('state')} at {clock(e['t'])}")
        else:
            out.append(f"Charging {'normal' if not e.get('hold') else e.get('hold')} at "
                       f"{clock(e['t'])}, battery about {e.get('celsius', 0):.0f} °C")
    for e in shutdowns:
        out.append(f"Switched itself off at {clock(e['t'])}: too hot" if e.get('why') == 'hot' else
                   f"Switched itself off at {clock(e['t'])}: battery low "
                   f"({e.get('mv', 0) / 1000:.2f} V)")
    if oopses:
        out.append('Kernel oops at ' + ', '.join(clock(t) for t in oopses) +
                   f' (details in .runtime/phone/private/logs/{day}/kernel.log)')
    for e in stops:
        how = {'battery': 'switched itself off, battery low',
               'oops': 'restarted itself after a kernel oops',
               'off': 'was switched off',
               'reboot': 'was restarted on purpose',
               'hot': 'switched itself off, too hot',
               }.get(e.get('why'), 'stopped without warning (a crash, the watchdog, '
                                   'a flat battery or a hard reset)')
        volts = f", {e['mv'] / 1000:.2f} V" if e.get('mv', -1) > 0 else ''
        doing = f" ({e['doing']})" if e.get('doing') else ''
        out.append(f"Before the boot at {clock(e['t'])}: {how}; "
                   f"last seen {clock(e['at'])}{volts}{doing}")
    return '\n'.join(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--library', type=Path, default=PRIVATE / 'scenes')
    parser.add_argument('--ssh-config', type=Path, default=PRIVATE / 'ssh_config')
    parser.add_argument('--host', help='SSH host (default: try ' + ', '.join(HOSTS) + ')')
    parser.add_argument('--binary', type=Path, default=ARM,
                        help='renderer to install when none is running')
    sub = parser.add_subparsers(dest='command', required=True)
    put = sub.add_parser('put', help='add or replace a scene from a Markdown file')
    put.add_argument('file', help="Markdown file, or '-' for standard input")
    put.add_argument('--at', type=int, help='position, 1 = first (default: keep or append)')
    put.add_argument('--show', action='store_true', help='bring the scene up')
    put.add_argument('--id', help='scene ID for a file without frontmatter')
    put.add_argument('--label', help='label for a file without frontmatter')
    put.add_argument('--accent', choices=('sage', 'cyan', 'amber', 'muted'))
    put.add_argument('-m', '--message', help='why, for the library history')
    remove = sub.add_parser('remove', help='take a scene off the phone')
    remove.add_argument('id')
    remove.add_argument('-m', '--message')
    show = sub.add_parser('show', help='bring a scene up, also after reboots')
    show.add_argument('id')
    sub.add_parser('list', help='library, history and what the phone shows')
    publish_cmd = sub.add_parser('publish', help='publish hand edits made in the library')
    publish_cmd.add_argument('-m', '--message')
    sub.add_parser('undo', help='return to the previous published scenes')
    preview = sub.add_parser('preview', help='render a scene locally at 640 x 960')
    preview.add_argument('scene', help='scene ID in the library, or a Markdown file')
    preview.add_argument('--out', type=Path, required=True)
    capture = sub.add_parser('capture', help="save what the phone's display shows")
    capture.add_argument('--out', type=Path, required=True)
    sync_cmd = sub.add_parser('sync', help='make the phone match the library')
    sync_cmd.add_argument('--receipt', type=Path)
    journal = sub.add_parser('journal', help='what was read on the phone, and the battery')
    journal.add_argument('action', nargs='?', choices=('pull',), help='copy it from the phone')
    journal.add_argument('--day', default=time.strftime('%Y-%m-%d'), help='YYYY-MM-DD')
    journal.add_argument('--dir', type=Path, default=JOURNAL)
    a = parser.parse_args()
    os.umask(0o077)
    if a.library == PRIVATE / 'scenes' and not PRIVATE.is_dir():
        raise Failure(f'{ROOT} has no phone state ({PRIVATE}). Run scene.py from the '
                      'checkout that boots the phone, or pass --library and --ssh-config')
    phone = Phone(a.ssh_config, a.host, a.binary)
    if a.command == 'journal':
        if a.action == 'pull':
            print(f'{journal_pull(phone, a.dir)} new journal entries.')
            return 0
        labels = {}
        for md in Path(a.library).glob('*.md'):
            head = md.read_text(encoding='utf-8', errors='replace').split('\n---\n', 1)[0]
            for line in head.splitlines():
                if line.startswith('label:'):
                    labels[md.stem] = line[6:].strip()
        print(journal_summary(a.dir, a.day, labels))
        return 0
    library = Library(a.library).open()

    if a.command == 'put':
        if Path(a.file).is_dir():
            if any(x is not None for x in (a.id, a.label, a.accent, a.at)):
                raise Failure('A bundle supplies its own IDs, labels and order')
            bundle = Path(a.file)
            check(bundle)
            ids = scene_ids((bundle / 'index').read_text())
            files = {i: (bundle / (i + '.md')).read_bytes() for i in ids}
            # Preserve phone-authored work before replacing the whole library.
            # Importing it after the edit would silently undo a deliberate removal.
            try:
                adopt(library, phone)
            except Unreachable:
                pass

            def edit_bundle():
                for p in library.path.glob('*.md'):
                    p.unlink()
                for i, data in files.items():
                    (library.path / (i + '.md')).write_bytes(data)
                library.write_index(ids)
            return change(library, phone, 'Replace scene bundle' +
                          (f': {a.message}' if a.message else ''), edit_bundle,
                          ids[0] if a.show else None, import_phone=False)
        scene_id, text = read_scene(a.file, a.id, a.label, a.accent)

        def edit():
            (library.path / f'{scene_id}.md').write_text(text, encoding='utf-8')
            ids = library.index()
            if scene_id in ids and a.at is not None:
                ids.remove(scene_id)
            if scene_id not in ids:
                ids.insert(len(ids) if a.at is None else max(a.at - 1, 0), scene_id)
            library.write_index(ids)
        verb = 'Replace' if scene_id in library.index() else 'Add'
        message = f'{verb} {scene_id}' + (f': {a.message}' if a.message else '')
        return change(library, phone, message, edit, scene_id if a.show else None)

    if a.command == 'remove':
        ids = library.index()
        if a.id not in ids:
            raise Failure(f'{a.id} is not in the library')
        if len(ids) == 1:
            raise Failure('The phone needs at least one scene')

        def edit():
            library.write_index([i for i in ids if i != a.id])
            (library.path / f'{a.id}.md').unlink(missing_ok=True)
        message = f'Remove {a.id}' + (f': {a.message}' if a.message else '')
        return change(library, phone, message, edit)

    if a.command == 'publish':
        message = 'Edit scenes' + (f': {a.message}' if a.message else '')
        return change(library, phone, message, lambda: None)

    if a.command == 'undo':
        if not library.git('rev-list', '--max-count=1', '--skip=1', 'HEAD').strip():
            raise Failure('Nothing to undo')
        if library.git('status', '--porcelain').strip():
            raise Failure('The library has unpublished edits; publish or discard them first')
        subject = library.git('log', '-1', '--format=%s').decode().strip()
        library.git('revert', '--no-edit', '--no-commit', 'HEAD')
        try:
            check(library.path)
        except Failure:
            library.git('reset', '-q', '--hard', 'HEAD')
            raise
        library.commit(f'Undo: {subject}')
        print(f'Saved in the scene library ({library.head()[:7]}).')
        return publish(library, phone)

    if a.command == 'show':
        if a.id not in scene_ids(library.files()['index'].decode()):
            raise Failure(f'{a.id} is not a published scene')
        library.focus_file.write_text(a.id + '\n')
        return publish(library, phone, a.id)

    if a.command == 'sync':
        print(sync(library, phone, receipt=a.receipt))
        return 0

    if a.command == 'preview':
        with tempfile.TemporaryDirectory() as tmp:
            bundle = library.path
            scene_id = a.scene
            if Path(a.scene).is_file():
                scene_id, text = read_scene(a.scene, None, None, None)
                bundle = Path(tmp) / 'scenes'
                bundle.mkdir()
                (bundle / 'index').write_text(scene_id + '\n')
                (bundle / f'{scene_id}.md').write_text(text, encoding='utf-8')
            check(bundle, scene_id)
            ppm = Path(tmp) / 'frame.ppm'
            sp.run([str(NATIVE), '--assets', str(ASSETS), '--scenes', str(bundle),
                    '--scene', scene_id, '--render', str(ppm)],
                   check=True, capture_output=True, timeout=60)
            ppm_to_png(ppm.read_bytes(), a.out)
        print(f'Rendered {scene_id} to {a.out}. Live values come from this computer.')
        return 0

    if a.command == 'capture':
        phone.run('rm -f /run/soy/frame.ppm')
        phone.command('capture')
        deadline = time.monotonic() + 10
        while phone.run('wc -c < /run/soy/frame.ppm 2>/dev/null || echo 0').strip() != \
                str(FRAME_BYTES).encode():
            if time.monotonic() > deadline:
                raise Failure('The phone did not capture a frame')
            time.sleep(0.3)
        ppm_to_png(phone.run('cat /run/soy/frame.ppm'), a.out)
        print(f'Saved the phone display to {a.out}.')
        return 0

    # list
    ids = library.index()
    head = library.git('log', '-1', '--format=%h %ad  %s', '--date=format:%Y-%m-%d %H:%M')
    print(f'Library {library.path}\n  {head.decode().strip()}')
    if library.git('status', '--porcelain').strip():
        print('  Unpublished edits in the library; run publish.')
    try:
        state = phone.state()
        files = library.files()
        shown = state['status'].get('scene', '')
        if not state['running']:
            print('Phone: the renderer is not running')
        else:
            sync_state = 'matches the library' if in_sync(state, files) else 'differs from the library'
            print(f'Phone ({phone.host}): showing {shown}; {sync_state}')
    except Unreachable as exc:
        shown = ''
        print(f'Phone: {exc}')
    focus = library.focus()
    for n, scene_id in enumerate(ids, 1):
        path = library.path / f'{scene_id}.md'
        text = path.read_text(encoding='utf-8') if path.exists() else ''
        label = next((line[6:].strip() for line in text.split('\n---\n', 1)[0].split('\n')
                      if line.startswith('label:')), scene_id)
        marks = ('>' if scene_id == shown else ' ') + ('*' if scene_id == focus else ' ')
        print(f'{marks}{n:3}  {scene_id:<16} {label:<24} {len(text.encode()) / 1024:6.1f} KiB')
    if focus:
        print('* opens after a reboot')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Failure as exc:
        print(f'scene.py: {exc}', file=sys.stderr)
        raise SystemExit(1)
