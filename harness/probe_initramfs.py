#!/usr/bin/env python3
"""Boot an unchanged phone initramfs with a QEMU reference kernel.

This covers the integrated /init -> BusyBox init -> Dropbear path, which the
overlay-on-ext4 probe does not exercise. It cannot test the N90 kernel, its
TUN module, loader, USB controller, or phone entropy. QEMU supplies a virtual
random source and network configuration comes from the reference kernel
command line, without modifying the archive.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess as sp
import time


def digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('initramfs', 'kernel', 'dtb', 'key', 'out'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    result = {
        'scope': 'QEMU reference kernel and virtio RNG, exact phone initramfs; '
                 'NOT phone boot, USB, TUN, or phone entropy evidence',
        'passed': False, 'inputs': {}, 'checks': {},
    }
    proc = None
    try:
        for name in ('initramfs', 'kernel', 'dtb'):
            source = getattr(args, name).resolve()
            before = digest(source)
            shutil.copyfile(source, out / name)
            if digest(out / name) != before or digest(source) != before:
                raise RuntimeError('Input changed while snapshotting: ' + name)
            result['inputs'][name] = {'sha256': before, 'bytes': source.stat().st_size}
        wrong = out / 'wrong-key'
        sp.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(wrong)],
               check=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        command = [
            'qemu-system-arm', '-M', 'vexpress-a9', '-smp', '1', '-m', '512',
            '-kernel', str(out / 'kernel'), '-dtb', str(out / 'dtb'),
            '-initrd', str(out / 'initramfs'),
            '-append', 'console=ttyAMA0,115200 rdinit=/init ip=dhcp',
            '-display', 'none', '-monitor', 'none', '-audio', 'none',
            '-serial', 'stdio', '-net', 'nic,model=lan9118',
            '-net', f'user,hostfwd=tcp:127.0.0.1:{port}-:22',
            '-object', 'rng-random,filename=/dev/urandom,id=rng0',
            '-device', 'virtio-rng-device,rng=rng0',
        ]
        result['qemu_command'] = command
        with (out / 'boot.log').open('w') as log, (out / 'ssh.log').open('w') as evidence:
            proc = sp.Popen(command, stdin=sp.DEVNULL, stdout=log, stderr=sp.STDOUT)

            def ssh(cmd, *, key=args.key.resolve(), pty=False, record=True):
                options = [
                    'ssh', '-F', '/dev/null', '-p', str(port), '-i', str(key),
                    '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
                    '-o', 'StrictHostKeyChecking=accept-new',
                    '-o', f'UserKnownHostsFile={out / "known_hosts"}',
                    '-o', 'ConnectTimeout=15',
                ]
                if pty:
                    options.append('-tt')
                master = slave = None
                try:
                    if pty:
                        # A terminal test needs a live terminal input. Immediate
                        # EOF can hang up the remote PTY before its command runs.
                        master, slave = os.openpty()
                    r = sp.run(options + ['root@127.0.0.1', cmd],
                               stdin=slave if pty else sp.DEVNULL,
                               text=True, capture_output=True, timeout=30)
                finally:
                    if master is not None:
                        os.close(master)
                        os.close(slave)
                if record:
                    evidence.write(f'$ {cmd}\nexit={r.returncode}\n{r.stdout}{r.stderr}\n')
                    evidence.flush()
                return r

            deadline = time.monotonic() + 150
            last = None
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError(f'QEMU exited with {proc.returncode}')
                # Wait for service startup before opening forwarded connections.
                if 'Starting dropbear sshd: OK' not in (out / 'boot.log').read_text():
                    time.sleep(1)
                    continue
                last = ssh('true', record=False)
                if last.returncode == 0:
                    break
                time.sleep(2)
            else:
                result['last_ssh_error'] = last.stderr if last else 'Dropbear startup not observed'
                raise RuntimeError('Integrated initramfs did not provide SSH within 150 seconds')
            checks = result['checks']
            checks['ssh_key_login'] = ssh('true').returncode == 0
            r = ssh('uname -m; cat /proc/1/comm; cat /proc/cmdline; '
                    'cat /proc/mounts; ps')
            result['guest'] = r.stdout
            checks['armv7_init'] = r.returncode == 0 and 'armv7l\ninit\n' in r.stdout
            checks['initramfs_entry'] = 'rdinit=/init' in r.stdout
            r = ssh('test -t 0 && test -t 1 && echo PTY_OK', pty=True)
            checks['ssh_pty'] = r.returncode == 0 and 'PTY_OK' in r.stdout
            value = os.urandom(32).hex()
            expected = hashlib.sha256(value.encode()).hexdigest()
            r = ssh(f"printf '%s' '{value}' > /tmp/master-probe; "
                    "sha256sum /tmp/master-probe; rm /tmp/master-probe")
            checks['file_io'] = (r.returncode == 0 and bool(r.stdout.split())
                                 and r.stdout.split()[0] == expected)
            r = ssh('true', key=wrong)
            checks['wrong_key_denied'] = (r.returncode == 255
                                           and 'Permission denied (publickey)' in r.stderr)
            checks['ssh_alive_after_denial'] = ssh('true').returncode == 0
            r = ssh('tailscale version; grep -w tun /proc/misc || true; '
                    "dmesg | grep -E 'tun|module|initramfs' | tail -20")
            result['tun_and_tailscale_observation'] = r.stdout
            result['passed'] = all(checks.values())
            if not result['passed']:
                raise RuntimeError('An integrated-initramfs check failed')
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except sp.TimeoutExpired:
                proc.kill()
                proc.wait()
        (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'passed': result['passed'], 'checks': result['checks'],
                      'error': result.get('error'), 'evidence': str(out)}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
