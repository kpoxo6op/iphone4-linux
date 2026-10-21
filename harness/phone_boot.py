#!/usr/bin/env python3
"""Unattended N90 boot: recovery -> DFU -> openiBoot -> Linux -> saved identity.

One bounded pass under the shared USB-operation lock. Each stage acts only
after observing the expected mode on the pinned USB socket, and has a deadline.
Loader and oibc run in a sandbox whose /dev/bus/usb holds only the pinned
phone's node. The DFU-IPSW route is the reviewed phone_dfu_restore procedure.

A fresh RAM boot generates a new Dropbear host key and has an empty
Tailscale state and a 1970 clock. The first SSH connection therefore uses a
throwaway known_hosts, but only on the point-to-point `iphone4` link that udev
names for the pinned socket, and only to install the saved host key, saved
tailscaled state and the host's time. Every later connection uses the saved
known_hosts strictly. No re-enrollment, no global trust change.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess as sp
import sys
import tempfile
import time

import control
import phone_watch

ROOT = control.ROOT
PRIVATE = control.STATE / 'phone/private'
KIT = PRIVATE / 'recovery-knownboot-20261021'
RUNS = PRIVATE / 'boot-runs'
RECORD = PRIVATE / 'boot.json'
LOCK = control.STATE / 'phone/usb-operation.lock'
SSH_CONFIG = PRIVATE / 'ssh_config'
LIVE = PRIVATE / 'live-state'
# Exact files of the 2026-10-21 knownboot (phone/recovery/knownboot-manifest.json)
# plus the oibc client that uploaded them.
KIT_SHA256 = {
    'zImage': '936edd3f9419d393993a03a061f05f3cd848fd8dcf0b16be1ad610add3db0563',
    'n90-boot.dtb': '5b8288fc08b604e3d4305e33f812cf29249baf5d37d881126862f1a9c7bf116a',
    'ramboot.bin': 'ebeff1d0f2d94d8419949eeae0e5522421c69f2461fb4573f21f14375c57ab79',
    'initramfs': '5513ddf992f8a74157a45265d2744ccee07d09d60cef0017aca65ce8c109ec1c',
    'openiboot.bin': '29d65d295aae4ce2318d30756e427dd9f177daf05280eaeafa7670cea6e22cb2',
    'loadibec-fixed': '944272832a88cfd5c7679c07e56abb610c6d6441826ba0c1eb792b7620181331',
    'oibc': '5083a208079bd93f7fa8e850ccc9625b95460f9ba9d32ccf963e3cb3e9221485',
    # Local-only Apple iBSS and its payload; loadibec reads both from its cwd.
    'iBSS.n90ap': 'fe45bf803a01277936c77276037c583022d180a4056d7a5a28b03a3fcd58a849',
    'iBSS.n90ap.payload': 'a8e1fe0039a72668a301160837a0e8d703544f454a0a11736a6ed9386fca5f9f',
}
UPLOADS = [('zImage', '0x01000000'), ('n90-boot.dtb', '0x0c000000'),
           ('ramboot.bin', '0x0c100000'), ('initramfs', '0x0d000000')]
ENTRY = '0x0c100000'
MAX_FAILURES = 3
# Test boots only: replace a knownboot upload with another file for one pass.
OVERRIDES = {}
# Preferred kernel: knownboot plus the N90 display-power drivers
# (kernel/n90-display-power), built lean (no lockdep or tracer, 24 MHz
# sched_clock, HZ 1000, uinput built in). After a failed pass with it, the
# next pass boots plain knownboot; a successful boot clears that. The record
# keeps calling it "backlight".
BACKLIGHT = PRIVATE / 'lean-20261022'
BACKLIGHT_SHA256 = {
    'zImage': 'e899dceb2bea264a3470aaa3647bc3a64b8c65736a00366ad43fd4ad4a745973',
    'n90-boot.dtb': '9567afd1d6328a3fac8a3372a3019a7a01195fc8c44d1062cd81fba0a3ff2754',
}


class StageFailed(Exception):
    pass


def log(run, stage, **fields):
    entry = {'at': datetime.now(timezone.utc).isoformat(), 'stage': stage, **fields}
    with (run / 'stages.jsonl').open('a') as f:
        f.write(json.dumps(entry) + '\n')
    print(json.dumps(entry), flush=True)


def save_record(value):
    temporary = RECORD.with_suffix('.new')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(RECORD)


def observe():
    policy = json.loads((PRIVATE / 'device-policy.json').read_text())
    value = phone_watch.observe(target=policy)
    if value['status'] == 'no_device':
        return 'no_device'
    if len(value['devices']) != 1:
        raise StageFailed('More than one candidate phone is attached')
    if value['status'] in ('dfu', 'recovery') and value.get('identity_source') != 'pinned ECID':
        raise StageFailed('Apple-mode device is not the pinned phone')
    return value['status']


def wait_for(run, modes, seconds):
    deadline = time.monotonic() + seconds
    seen = None
    while time.monotonic() < deadline:
        try:
            seen = observe()
        except (OSError, ValueError, KeyError):
            seen = 'unreadable'
        if seen in modes:
            return seen
        time.sleep(2)
    log(run, 'timeout', expected=sorted(modes), last=seen, seconds=seconds)
    raise StageFailed(f'Expected {sorted(modes)} within {seconds}s; last saw {seen}')


def verify_kit():
    for name, expected in KIT_SHA256.items():
        with (KIT / name).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                raise StageFailed(f'{name} does not match the knownboot hash')


def pinned_usb(run, args, stdin=None):
    """Run a USB tool that can see only the pinned phone's device node."""
    sandbox = ['bwrap', '--die-with-parent', '--unshare-pid', '--unshare-ipc',
               '--ro-bind', '/usr', '/usr', '--symlink', 'usr/lib', '/lib',
               '--symlink', 'usr/lib64', '/lib64', '--symlink', 'usr/bin', '/bin',
               '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
               '--ro-bind', '/etc/ld.so.cache', '/etc/ld.so.cache',
               '--ro-bind', '/sys', '/sys', '--ro-bind', '/run/udev', '/run/udev',
               '--dev-bind', '/dev/iphone4-worker-usb', '/dev/bus/usb',
               '--ro-bind', str(KIT), str(KIT), '--bind', str(run), str(run),
               '--chdir', str(run), '--']
    name = Path(args[0]).name
    with (run / f'{name}.log').open('ab') as output:
        process = sp.Popen(sandbox + args, stdin=sp.PIPE if stdin else sp.DEVNULL,
                           stdout=output, stderr=sp.STDOUT)
        if stdin:
            process.stdin.write(stdin.encode())
            process.stdin.close()
    return process


def dfu_from_recovery(run):
    """Reuse the reviewed DFU-IPSW route; it ends in hardware DFU."""
    import phone_dfu_restore as restore
    restore.verify_tools()
    mode, ecid = restore.identity()
    if mode != 'recovery':
        raise StageFailed('Phone left recovery before the restore')
    artifact = restore.WORK / 'iPhone3,1_7.1.2_11D257_DFU.ipsw'
    recorded = json.loads((restore.WORK / 'artifact.json').read_text())
    with artifact.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != recorded['modified_sha256']:
            artifact = restore.prepare()
    env = dict(os.environ, LD_LIBRARY_PATH=str(restore.KIT / 'lib'))
    log(run, 'recovery_to_dfu', tool='idevicerestore DFU-IPSW')
    with (run / 'idevicerestore.log').open('wb') as output:
        result = sp.run([str(restore.KIT / 'idevicerestore'), '-e', '-y', '-i', ecid,
                         '-C', str(restore.WORK / 'restore-cache'), str(artifact)],
                        cwd=restore.WORK, env=env, stdout=output, stderr=sp.STDOUT,
                        timeout=1200)
    # The intended LLB write error makes idevicerestore exit non-zero.
    log(run, 'restore_exit', returncode=result.returncode)
    wait_for(run, {'dfu'}, 120)


def dfu_to_openiboot(run):
    # Without iBSS in its working directory the loader tries Apple's servers,
    # then sends openiBoot straight to DFU, which fails.
    for name in ('iBSS.n90ap', 'iBSS.n90ap.payload'):
        (run / name).write_bytes((KIT / name).read_bytes())
    log(run, 'loader_start')
    loader = pinned_usb(run, [str(KIT / 'loadibec-fixed'), str(KIT / 'openiboot.bin')])
    try:
        returncode = loader.wait(timeout=240)
    except sp.TimeoutExpired:
        loader.kill()
        raise StageFailed('DFU loader did not finish within 240s')
    log(run, 'loader_end', returncode=returncode)
    # openiBoot appeared about 205 s after the loader on 2026-10-21.
    wait_for(run, {'openiboot'}, 420)


def openiboot_to_linux(run):
    paths = {}
    for name, _ in UPLOADS:
        paths[name] = KIT / name
        if name in OVERRIDES:
            data = Path(OVERRIDES[name]).read_bytes()
            paths[name] = run / ('test-' + name)
            paths[name].write_bytes(data)
            log(run, 'test_override', file=name, sha256=hashlib.sha256(data).hexdigest())
    commands = ''.join(f'!{paths[name]}@{address}\n' for name, address in UPLOADS)
    commands += f'go {ENTRY}\n'
    # oibc exits at once if openiBoot is not accepting connections yet; after
    # a successful `go` it never exits, and Linux USB enumeration is the result.
    for attempt in range(1, 4):
        time.sleep(20)
        log(run, 'upload_start', attempt=attempt)
        client = pinned_usb(run, [str(KIT / 'oibc')], stdin=commands)
        try:
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                if observe() == 'linux_usb':
                    log(run, 'linux_usb')
                    return
                if client.poll() is not None:
                    break
                time.sleep(2)
            else:
                raise StageFailed('Linux USB did not appear within 600s of the upload')
        finally:
            if client.poll() is None:
                client.terminate()
                try:
                    client.wait(timeout=10)
                except sp.TimeoutExpired:
                    client.kill()
        log(run, 'oibc_exited', returncode=client.returncode)
        if wait_for(run, {'openiboot', 'linux_usb'}, 60) == 'linux_usb':
            log(run, 'linux_usb')
            return
    raise StageFailed('oibc could not upload to openiBoot after three attempts')


def ssh(alias, command, known_hosts=None, timeout=30, stdin=None):
    args = ['ssh', '-F', str(SSH_CONFIG), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8']
    if known_hosts:
        args += ['-o', f'UserKnownHostsFile={known_hosts}', '-o', 'StrictHostKeyChecking=accept-new']
    else:
        args += ['-o', 'StrictHostKeyChecking=yes']
    return sp.run(args + [alias, command], input=stdin, capture_output=True, timeout=timeout)


def link_is_pinned():
    # udev names the interface `iphone4` only for the gadget on socket 3-4.
    try:
        device = Path('/sys/class/net/iphone4/device').resolve()
    except OSError:
        return False
    return '/usb3/3-4/' in str(device) + '/'


def claim_usb_address(run):
    """Give the phone 10.84.4.2 when DHCP handed it a spare address.

    NetworkManager keeps a lease for the previous boot's gadget MAC. A reboot
    releases it, but a reset (watchdog, panic, freeze) does not, so the new
    boot is offered the spare 10.84.4.3 until that lease ends. On the pinned
    link only, add the expected address next to it over a first-contact
    connection, as the fresh-boot identity step already does.
    """
    for spare in SPARE_USB_ADDRESSES:
        if not port_open(spare):
            continue
        with tempfile.TemporaryDirectory() as temporary:
            fresh = Path(temporary) / 'known_hosts'
            args = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
                    '-o', f'UserKnownHostsFile={fresh}', '-o', 'StrictHostKeyChecking=accept-new',
                    '-i', str(PRIVATE / 'ssh_ed25519'), f'root@{spare}',
                    "tr -d '\\000' < /proc/device-tree/model; "
                    'ip addr add 10.84.4.2/24 dev usb0 2>/dev/null; true']
            result = sp.run(args, capture_output=True, timeout=30)
        if result.returncode == 0 and result.stdout.decode().startswith('Apple iPhone 4'):
            log(run, 'usb_address_claimed', spare=spare)
            return True
    return False


def restore_identity(run):
    """Install the saved host key, Tailscale state and host time on a fresh boot."""
    deadline = time.monotonic() + 180
    while not (link_is_pinned() and (ssh_port_open() or claim_usb_address(run))):
        if time.monotonic() > deadline:
            raise StageFailed('USB SSH did not come up on the pinned link')
        time.sleep(3)
    if ssh('iphone4-usb', 'true').returncode == 0:
        log(run, 'identity_already_present')
    else:
        with tempfile.TemporaryDirectory() as temporary:
            fresh = Path(temporary) / 'known_hosts'
            probe = ssh('iphone4-usb', "tr -d '\\000' < /proc/device-tree/model", fresh)
            if probe.returncode or probe.stdout.decode().strip() != 'Apple iPhone 4':
                raise StageFailed('Fresh boot did not identify as the iPhone 4')
            for name, target in (('tailscaled.state', '/tmp/.ts.saved'),
                                 ('dropbear_ed25519_host_key', '/tmp/.hk.saved')):
                sent = ssh('iphone4-usb', f'umask 077; cat > {target}', fresh,
                           stdin=(LIVE / name).read_bytes())
                if sent.returncode:
                    raise StageFailed(f'Could not stage {name}')
            script = (
                f'date -s @{int(time.time())} >/dev/null && '
                '/etc/init.d/S99tailscaled stop >/dev/null; '
                'cp /tmp/.ts.saved /var/lib/tailscale/tailscaled.state && '
                'cp /tmp/.hk.saved /etc/dropbear/dropbear_ed25519_host_key && '
                'rm -f /tmp/.ts.saved /tmp/.hk.saved && '
                '/etc/init.d/S99tailscaled start >/dev/null && '
                # Restart only the listener; this session's child keeps running.
                '(sleep 1; kill $(cat /var/run/dropbear.pid); sleep 1; '
                '/usr/sbin/dropbear -s -g -R) >/dev/null 2>&1 </dev/null &')
            result = ssh('iphone4-usb', script, fresh)
            if result.returncode:
                raise StageFailed('Identity installation failed on the phone')
        log(run, 'identity_installed')
    # Dropbear restarts in the background; allow it time to listen again.
    deadline = time.monotonic() + 60
    while (checked := ssh('iphone4-usb', 'cat /proc/sys/kernel/random/boot_id; date +%s')).returncode:
        if time.monotonic() > deadline:
            raise StageFailed('Saved host key did not verify over USB')
        time.sleep(3)
    boot_id, clock = checked.stdout.decode().split()[:2]
    if abs(int(clock) - time.time()) > 120:
        ssh('iphone4-usb', f'date -s @{int(time.time())} >/dev/null')
    log(run, 'usb_ssh_verified', boot_id=boot_id)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        tailnet = ssh('iphone4', 'cat /proc/sys/kernel/random/boot_id')
        if tailnet.returncode == 0 and tailnet.stdout.decode().strip() == boot_id:
            log(run, 'tailnet_ssh_verified', boot_id=boot_id)
            return boot_id
        time.sleep(10)
    raise StageFailed('Phone did not reach the tailnet with its saved identity')


SPARE_USB_ADDRESSES = ('10.84.4.3',)


def port_open(address):
    import socket
    try:
        with socket.create_connection((address, 22), timeout=3):
            return True
    except OSError:
        return False


def ssh_port_open():
    return port_open('10.84.4.2')


def choose_kernel(run, record):
    if OVERRIDES:
        return 'test'
    if record.get('backlight_failures', 0):
        log(run, 'kernel', choice='knownboot', reason='backlight kernel failed last pass')
        return 'knownboot'
    for name, expected in BACKLIGHT_SHA256.items():
        path = BACKLIGHT / name
        if not path.exists():
            log(run, 'kernel', choice='knownboot', reason='backlight kernel absent')
            return 'knownboot'
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                raise StageFailed(f'Backlight {name} does not match its hash')
        OVERRIDES[name] = str(path)
    log(run, 'kernel', choice='backlight')
    return 'backlight'


def boot(run, record):
    mode = observe()
    log(run, 'observed', mode=mode)
    if mode == 'no_device':
        raise StageFailed('No phone on the pinned socket')
    if mode == 'normal':
        # A booted iOS can be asked to restart into recovery over lockdown.
        udids = sp.run(['idevice_id', '-l'], capture_output=True, text=True,
                       timeout=20).stdout.split()
        if len(udids) != 1:
            raise StageFailed('Expected exactly one iOS device in normal mode')
        log(run, 'normal_to_recovery')
        sp.run(['ideviceenterrecovery', udids[0]], capture_output=True, timeout=60)
        mode = wait_for(run, {'recovery', 'dfu'}, 180)
    if mode == 'recovery':
        dfu_from_recovery(run)
        mode = 'dfu'
    if mode in ('dfu', 'openiboot'):
        verify_kit()
        record['kernel'] = choose_kernel(run, record)
    if mode == 'dfu':
        dfu_to_openiboot(run)
        mode = 'openiboot'
    if mode == 'openiboot':
        openiboot_to_linux(run)
        mode = 'linux_usb'
    if mode != 'linux_usb':
        raise StageFailed(f'No automatic route from mode {mode}')
    boot_id = restore_identity(run)
    deploy_watchdog(run)
    deploy_display(run)
    deploy_touch(run)
    return boot_id


def deploy_display(run):
    """RAM boots lose Soy; reinstall the current build. Not a boot failure."""
    binary = ROOT / 'output/soy/lvgl-armv7/soy'
    if not binary.exists():
        log(run, 'display_skipped', reason='no ARM Soy build')
        return
    result = sp.run([sys.executable, str(ROOT / 'soy/tools/deploy.py'),
                     '--ssh-config', str(SSH_CONFIG), '--host', 'iphone4-usb',
                     '--binary', str(binary), '--receipt', str(run / 'soy-deploy.json')],
                    capture_output=True, timeout=300)
    log(run, 'display_deployed' if result.returncode == 0 else 'display_failed',
        returncode=result.returncode)


def deploy_watchdog(run):
    """Arm the SoC watchdog (kernel/n90-watchdog) so a frozen kernel resets.

    A reset lands in DFU, where the watcher starts the next pass. Not a boot
    failure if it cannot start.
    """
    binary = ROOT / 'output/watchdog/n90-wdt'
    if not binary.exists():
        log(run, 'watchdog_skipped', reason='no n90-wdt build')
        return
    sent = ssh('iphone4-usb', 'killall n90-wdt 2>/dev/null; sleep 1; '
               'cat > /usr/sbin/n90-wdt.new && chmod 755 /usr/sbin/n90-wdt.new && '
               'mv /usr/sbin/n90-wdt.new /usr/sbin/n90-wdt',
               stdin=binary.read_bytes())
    started = sent.returncode == 0 and ssh(
        'iphone4-usb', 'nohup /usr/sbin/n90-wdt 60 10 >/run/n90-wdt.log 2>&1 </dev/null & '
        'sleep 1; pidof n90-wdt').returncode == 0
    log(run, 'watchdog_armed' if started else 'watchdog_failed')


TOUCH_FIRMWARE = PRIVATE / 'touch/n90-z2-0x0098.bin'


def deploy_touch(run):
    """Start the physical touch driver (kernel/n90-touch). Not a boot failure."""
    binary = ROOT / 'output/touch/n90-touch'
    if not binary.exists() or not TOUCH_FIRMWARE.exists():
        log(run, 'touch_skipped', reason='no n90-touch build or firmware')
        return
    args = [sys.executable, str(ROOT / 'kernel/n90-touch/deploy.py'),
            '--ssh-config', str(SSH_CONFIG), '--host', 'iphone4-usb',
            '--binary', str(binary), '--firmware', str(TOUCH_FIRMWARE)]
    module = ROOT / 'output/touch/uinput.ko'
    if module.exists():
        args += ['--uinput-ko', str(module)]
    result = sp.run(args, capture_output=True, timeout=120)
    log(run, 'touch_started' if result.returncode == 0 else 'touch_failed',
        returncode=result.returncode, detail=result.stderr.decode()[-300:])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('run', 'status', 'reset-failures'))
    parser.add_argument('--test-zimage', help='boot this kernel instead, once')
    parser.add_argument('--test-dtb', help='boot this device tree instead, once')
    args = parser.parse_args()
    if args.test_zimage:
        OVERRIDES['zImage'] = args.test_zimage
    if args.test_dtb:
        OVERRIDES['n90-boot.dtb'] = args.test_dtb
    os.umask(0o077)
    if args.command == 'status':
        print(RECORD.read_text() if RECORD.exists() else '{}')
        return
    record = json.loads(RECORD.read_text()) if RECORD.exists() else {}
    if args.command == 'reset-failures':
        record.update(failures=0, backlight_failures=0)
        save_record(record)
        return
    if record.get('failures', 0) >= MAX_FAILURES:
        raise SystemExit('Three consecutive boot failures; inspect boot-runs, then reset-failures')
    with open(LOCK, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another phone USB operation is running')
        RUNS.mkdir(parents=True, exist_ok=True)
        run = RUNS / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        run.mkdir()
        try:
            boot_id = boot(run, record)
        except (StageFailed, OSError, sp.SubprocessError) as exc:
            log(run, 'failed', error=str(exc)[:300])
            if record.get('kernel') == 'backlight':
                record['backlight_failures'] = record.get('backlight_failures', 0) + 1
            record.update(failures=record.get('failures', 0) + 1, last_run=run.name,
                          last_result='failed', last_error=str(exc)[:300])
            save_record(record)
            raise SystemExit(1)
        record.pop('last_error', None)
        if record.get('kernel') == 'backlight':
            record['backlight_failures'] = 0
        record.update(failures=0, last_run=run.name, last_result='ready', boot_id=boot_id,
                      ready_at=datetime.now(timezone.utc).isoformat())
        save_record(record)


if __name__ == '__main__':
    main()
