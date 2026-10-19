#!/usr/bin/env python3
"""Real ARM boot/SSH/disk acceptance; deliberately independent of build scripts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess as sp
import tempfile
import time


def run(args, **kw):
    return sp.run(args, check=True, text=True, capture_output=True, **kw)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--images', required=True, type=Path)
    p.add_argument('--results', type=Path, default=Path('output/acceptance'))
    a = p.parse_args()
    a.images = a.images.resolve()
    a.results.mkdir(parents=True, exist_ok=True)
    for name in ('zImage', 'vexpress-v2p-ca9.dtb', 'rootfs.ext4'):
        if not (a.images / name).is_file():
            p.error(f'missing real artifact: {a.images / name}')
    debugfs = shutil.which('debugfs') or '/usr/sbin/debugfs'
    result = {'scope': 'QEMU vexpress-a9 only; NOT iPhone hardware', 'passed': False}
    proc = None
    log = None
    try:
        with tempfile.TemporaryDirectory(prefix='qemu-', dir=a.results) as td:
            d = Path(td).resolve()
            disk = d / 'rootfs.ext4'
            shutil.copyfile(a.images / 'rootfs.ext4', disk)
            for key in ('key', 'wrong'):
                run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(d / key)])
            # debugfs may return zero on an invalid command; SSH below verifies insertion.
            for command in ('mkdir /root/.ssh', 'rm /root/.ssh/authorized_keys',
                            f'write {d}/key.pub /root/.ssh/authorized_keys',
                            'set_inode_field /root/.ssh mode 040700',
                            'set_inode_field /root/.ssh/authorized_keys mode 0100600'):
                run([debugfs, '-w', '-R', command, str(disk)])
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            def ssh(command, key='key', check=True):
                return sp.run(['ssh', '-p', str(port), '-i', str(d / key),
                    '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
                    '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
                    '-o', 'ConnectTimeout=3', 'root@127.0.0.1', command],
                    text=True, capture_output=True, timeout=15, check=check)
            def boot(number):
                nonlocal proc, log
                log = open(a.results / f'boot-{number}.log', 'w')
                proc = sp.Popen(['qemu-system-arm', '-M', 'vexpress-a9', '-smp', '1',
                    '-m', '512', '-kernel', str(a.images / 'zImage'), '-dtb',
                    str(a.images / 'vexpress-v2p-ca9.dtb'), '-drive',
                    f'file={disk},if=sd,format=raw', '-append',
                    'console=ttyAMA0,115200 rootwait root=/dev/mmcblk0 rw',
                    '-display', 'none', '-monitor', 'none', '-serial', 'stdio',
                    '-net', 'nic,model=lan9118', '-net',
                    f'user,hostfwd=tcp:127.0.0.1:{port}-:22'],
                    stdin=sp.DEVNULL, stdout=log, stderr=sp.STDOUT)
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        raise RuntimeError(f'QEMU exited {proc.returncode}; see boot log')
                    if ssh('true', check=False).returncode == 0:
                        return
                    time.sleep(2)
                raise RuntimeError('SSH never became ready; see boot log')
            def shutdown():
                nonlocal proc, log
                ssh('sync; poweroff', check=False)
                proc.wait(timeout=45)
                log.close()
                proc = None
            boot(1)
            result['uname'] = ssh('uname -a').stdout.strip()
            assert ssh('uname -m').stdout.strip() == 'armv7l', result['uname']
            assert ssh('true', key='wrong', check=False).returncode != 0, 'wrong SSH key accepted'
            nonce = secrets.token_hex(32)
            expected = hashlib.sha256(nonce.encode()).hexdigest()
            ssh(f"printf %s {nonce} > /root/acceptance-file; sync")
            assert ssh('sha256sum /root/acceptance-file').stdout.split()[0] == expected
            shutdown()
            boot(2)
            assert ssh('sha256sum /root/acceptance-file').stdout.split()[0] == expected
            result['checks'] = ['ARMv7 boot', 'SSH public key', 'wrong key rejected',
                                'file write/read', 'file survives clean power cycle']
            shutdown()
            result['passed'] = True
    except Exception as exc:
        result['error'] = str(exc)
        raise
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except sp.TimeoutExpired:
                proc.kill()
                proc.wait()
        if log is not None and not log.closed:
            log.close()
        (a.results / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result))


if __name__ == '__main__':
    main()
