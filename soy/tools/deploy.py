#!/usr/bin/env python3
"""Validate and switch a Soy release over owner SSH, retaining rollback.

Only the owned display process is stopped. SSH and Tailscale remain independent.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess as sp
import tarfile
import time
import uuid


def sha(data):
    return hashlib.sha256(data).hexdigest()


p = argparse.ArgumentParser()
p.add_argument('--ssh-config', type=Path, required=True)
p.add_argument('--host', default='iphone4')
p.add_argument('--binary', type=Path, required=True)
p.add_argument('--scene', default='reader')
p.add_argument('--receipt', type=Path, required=True)
a = p.parse_args()
if not re.fullmatch(r'[A-Za-z0-9_-]+', a.scene):
    p.error('Invalid scene ID')
root = Path(__file__).resolve().parents[1]
repo = root.parent
revision = sp.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
dirty = bool(sp.check_output(['git', 'status', '--porcelain', '--', 'soy'], cwd=repo))
payload = {'soy': a.binary.read_bytes()}
for folder in ('assets', 'scenes'):
    for path in sorted((root / folder).rglob('*')):
        if path.is_symlink():
            raise SystemExit('Symlinks are not scene bundle inputs')
        if path.is_file():
            name = path.relative_to(root).as_posix()
            if not re.fullmatch(r'[A-Za-z0-9_./-]+', name):
                raise SystemExit('Unsupported bundle filename')
            payload[name] = path.read_bytes()
manifest = {
    'git_revision': revision,
    'uncommitted_soy': dirty,
    'binary_sha256': sha(payload['soy']),
    'files': {name: sha(data) for name, data in payload.items() if name != 'soy'},
}
payload['manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
release = ('prototype-' if dirty else revision[:12] + '-') + sha(payload['manifest.json'])[:12]
payload['SHA256SUMS'] = ''.join(
    f'{sha(data)}  {name}\n' for name, data in payload.items()
).encode()
buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode='w', format=tarfile.USTAR_FORMAT) as tar:
    for name, data in payload.items():
        info = tarfile.TarInfo(name)
        info.size = len(data)
        info.mode = 0o700 if name == 'soy' else 0o600
        tar.addfile(info, io.BytesIO(data))
ssh = ['ssh', '-F', str(a.ssh_config.resolve()), '-o', 'BatchMode=yes',
       '-o', 'ConnectTimeout=10', a.host]


def remote(command, data=None, timeout=45):
    result = sp.run(ssh + [command], input=data, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace')[-1200:] or
                           f'Remote exit {result.returncode}')
    return result.stdout


def stop_owned():
    remote('''if [ -f /run/soy/renderer.pid ]; then
 p=$(cat /run/soy/renderer.pid)
 case "$p" in ''|*[!0-9]*) exit 1;; esac
 if kill -0 "$p" 2>/dev/null; then
  case "$(readlink /proc/$p/exe)" in /opt/soy/releases/*/soy) ;; *)
   echo "Unexpected renderer owner" >&2; exit 1;; esac
  kill "$p"
  i=0; while kill -0 "$p" 2>/dev/null; do
   i=$((i+1)); [ "$i" -lt 50 ] || exit 1; sleep .1
  done
 fi
fi''', timeout=15)


def start(scene):
    remote(f'''rm -f /run/soy/status.json
nohup /opt/soy/current/soy --assets /opt/soy/current/assets --scenes /opt/soy/current/scenes --run /run/soy --scene {scene} >/var/log/soy.log 2>&1 </dev/null &
echo $! > /run/soy/renderer.pid''', timeout=15)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            result = json.loads(remote(
                'p=$(cat /run/soy/renderer.pid); kill -0 "$p" && cat /run/soy/status.json',
                timeout=12))
            if result['backend'] in ('framebuffer', 'simpledrm') and result['scene'] == scene:
                return result
        except (RuntimeError, json.JSONDecodeError):
            pass
        time.sleep(.2)
    raise RuntimeError('New renderer did not become ready')


previous = remote('readlink /opt/soy/current 2>/dev/null || true').decode().strip()
if previous and not re.fullmatch(r'releases/[A-Za-z0-9-]+', previous):
    raise SystemExit('Unexpected prior release path')
previous_scene = 'reader'
if previous:
    prior_status = json.loads(remote('cat /run/soy/status.json'))
    previous_scene = prior_status['scene']
    if not re.fullmatch(r'[A-Za-z0-9_-]+', previous_scene):
        raise SystemExit('Unexpected previous scene ID')
record = {'release': release, 'manifest': manifest, 'state': 'staging'}
a.receipt.parent.mkdir(parents=True, exist_ok=True)
stage = '/opt/soy/releases/.incoming-' + uuid.uuid4().hex
destination = '/opt/soy/releases/' + release
switch_attempted = False
try:
    a.receipt.write_text(json.dumps(record, indent=2) + '\n')
    remote(f'''set -e
umask 077
mkdir -p {stage} /run/soy /var/log
tar -xf - -C {stage}
cd {stage}
sha256sum -c SHA256SUMS >/dev/null
./soy --check --assets assets --scenes scenes --scene {a.scene}
if [ -e {destination} ]; then
 cd {destination}
 sha256sum -c {stage}/SHA256SUMS >/dev/null
 rm -rf {stage}
else
 mv {stage} {destination}
fi''', buf.getvalue())
    record['bundle_verified'] = True
    stop_owned()
    switch_attempted = True
    remote(f'''set -e
rm -f /opt/soy/current.new
ln -s releases/{release} /opt/soy/current.new
mv -Tf /opt/soy/current.new /opt/soy/current''')
    record['status'] = start(a.scene)
    record['state'] = 'running'
    if previous and previous != f'releases/{release}':
        remote(f'''set -e
rm -f /opt/soy/previous.new
ln -s {previous} /opt/soy/previous.new
mv -Tf /opt/soy/previous.new /opt/soy/previous''')
except Exception as exc:
    record['state'] = 'failed'
    record['error'] = str(exc)
    if switch_attempted and previous:
        try:
            stop_owned()
            remote(f'''set -e
rm -f /opt/soy/current.rollback
ln -s {previous} /opt/soy/current.rollback
mv -Tf /opt/soy/current.rollback /opt/soy/current''')
            record['rollback_status'] = start(previous_scene)
            record['state'] = 'rolled_back'
        except Exception as recovery:
            record['rollback_error'] = str(recovery)
finally:
    # This path is unique to this invocation and never a live release.
    try:
        remote(f'rm -rf {stage}')
    except Exception as cleanup:
        record['cleanup_error'] = str(cleanup)
    a.receipt.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps({k: record[k] for k in ('release', 'state')}))
raise SystemExit(0 if record['state'] == 'running' else 1)
