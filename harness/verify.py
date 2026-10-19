#!/usr/bin/env python3
"""Drive the independent QEMU harness and bind its evidence to image hashes."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

IMAGES = ('zImage', 'vexpress-v2p-ca9.dtb', 'rootfs.ext4')
TOOLS = ('qemu-system-arm', 'ssh', 'ssh-keygen', 'debugfs')


def hashes(images):
    result = {}
    for name in IMAGES:
        with (images / name).open('rb') as source:
            result[name] = hashlib.file_digest(source, 'sha256').hexdigest()
    return result


def doctor(images):
    missing = [name for name in IMAGES if not (images / name).is_file()
               or (images / name).stat().st_size == 0]
    tools = {name: shutil.which(name) for name in TOOLS}
    report = {'scope': 'QEMU prerequisites only; no boot or phone proof',
              'status': 'blocked' if missing or not all(tools.values()) else 'ready',
              'missing_images': missing, 'tools': tools}
    if not missing:
        report['sha256'] = hashes(images)
    return report


def drive(images, results):
    results.mkdir(parents=True, exist_ok=True)
    with (results / '.qemu.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
        run = Path(tempfile.mkdtemp(prefix=stamp, dir=results)).resolve()
        receipt = {'scope': 'QEMU vexpress-a9 only; NOT iPhone hardware',
                   'passed': False, 'doctor': doctor(images)}
        snapshot = run / 'images'
        try:
            if receipt['doctor']['status'] != 'ready':
                receipt['error'] = 'Missing prerequisites; see doctor'
                return 2, run
            snapshot.mkdir()
            for name in IMAGES:
                shutil.copyfile(images / name, snapshot / name)
            receipt['sha256'] = hashes(snapshot)
            if receipt['sha256'] != receipt['doctor']['sha256']:
                raise RuntimeError('Images changed during snapshot; retry after the build finishes')
            harness = Path(__file__).with_name('qemu_smoke.py')
            receipt['harness_sha256'] = hashlib.sha256(harness.read_bytes()).hexdigest()
            command = [sys.executable, str(harness), '--images', str(snapshot),
                       '--results', str(run)]
            receipt['command'] = command
            with (run / 'harness.log').open('w') as log:
                completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
            receipt['exit_code'] = completed.returncode
            raw = run / 'result.json'
            receipt['result'] = json.loads(raw.read_text()) if raw.exists() else None
            receipt['passed'] = (completed.returncode == 0 and
                                 isinstance(receipt['result'], dict) and
                                 receipt['result'].get('passed') is True)
            return (0 if receipt['passed'] else 1), run
        except Exception as exc:
            receipt['error'] = str(exc)
            return 1, run
        finally:
            shutil.rmtree(snapshot, ignore_errors=True)
            receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
            (run / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('doctor', 'qemu'))
    parser.add_argument('--images', type=Path, required=True)
    parser.add_argument('--results', type=Path, default=Path('output/verification'))
    args = parser.parse_args()
    try:
        if args.command == 'doctor':
            report = doctor(args.images)
            print(json.dumps(report, indent=2))
            return 0 if report['status'] == 'ready' else 2
        code, run = drive(args.images, args.results)
        print(json.dumps({'receipt': str(run / 'receipt.json'), 'exit_code': code}))
        return code
    except BlockingIOError:
        print('Another QEMU verification owns this results directory', file=sys.stderr)
        return 2
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
