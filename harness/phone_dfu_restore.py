#!/usr/bin/env python3
"""One owner-authorized, pinned N90 DFU-IPSW restore; never a retry loop.

Implements Legacy iOS Kit restore.sh device_dfuipsw at revision
23622f8fe72c09952089d5145a7b008cfcc90d9b: replace LLB with AppleLogo, then
perform an erase restore from recovery. The expected result is hardware DFU,
not a successful iOS restore or a running Linux system. Apple bytes stay private.
"""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess as sp
import time
import zipfile

import phone_watch
import usb_device_nodes

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = ROOT / '.runtime/phone/private'
WORK = PRIVATE / 'software-boot-20261021'
SOURCE = PRIVATE / 'firmware/iPhone3,1_7.1.2_11D257_Restore.ipsw'
SOURCE_SHA = '8df4acce2cc2989ad159f980dd65a4bdc8c9eab4000e35169baa70ceb8749b2d'
KIT = ROOT / '.cache/recovery-research'
REV = '23622f8fe72c09952089d5145a7b008cfcc90d9b'


def status(phase, **fields):
    record = {'phase': phase, 'updated_at': time.time(), **fields}
    temporary = WORK / 'status.new'
    temporary.write_text(json.dumps(record, indent=2) + '\n')
    temporary.replace(WORK / 'status.json')
    handoff = ROOT / '.cache/handoff/software-boot-status.json'
    public_temp = handoff.with_suffix('.new')
    public_temp.write_text(json.dumps(record, indent=2) + '\n')
    public_temp.replace(handoff)
    print(json.dumps(record), flush=True)


def identity():
    policy = json.loads((PRIVATE / 'device-policy.json').read_text())
    observation = phone_watch.observe(target=policy)
    if len(observation['devices']) != 1 or observation.get('identity_source') != 'pinned ECID':
        raise RuntimeError('Pinned phone identity is absent or ambiguous')
    if observation['identity'].get('HardwareModel') != 'N90AP':
        raise RuntimeError('Phone model does not match N90AP')
    path = Path('/sys' + policy['devpath'])
    serial = (path / 'serial').read_text()
    if not usb_device_nodes.matches(policy, policy['devpath'],
                                   (path / 'idVendor').read_text().strip(),
                                   (path / 'idProduct').read_text().strip(), serial):
        raise RuntimeError('Live USB identity failed its pinned check')
    ecid = re.search(r'\bECID:([0-9a-fA-F]+)', serial).group(1)
    return observation['status'], str(int(ecid, 16))


def verify_tools():
    tree = json.loads((KIT / 'legacy-tree.json').read_text())
    if tree['sha'] != REV:
        raise RuntimeError('Unexpected tool source revision')
    for name in ('idevicerestore', 'lib/libssl.so.35', 'lib/libcrypto.so.35'):
        data = (KIT / name).read_bytes()
        expected = next(x['sha'] for x in tree['tree']
                        if x['path'] == 'bin/linux/x86_64/' + name)
        actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if actual != expected:
            raise RuntimeError('Downloaded tool does not match pinned Git blob')


def prepare():
    with SOURCE.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != SOURCE_SHA:
            raise RuntimeError('Original Apple firmware digest mismatch')
    with zipfile.ZipFile(SOURCE) as archive:
        manifest = plistlib.loads(archive.read('BuildManifest.plist'))
        if manifest['SupportedProductTypes'] != ['iPhone3,1'] or manifest['ProductBuildVersion'] != '11D257':
            raise RuntimeError('Firmware is not the expected iPhone3,1 build')
        choices = [i for i in manifest['BuildIdentities']
                   if i['Info'].get('DeviceClass') == 'n90ap'
                   and i['Info'].get('RestoreBehavior') == 'Erase']
        if len(choices) != 1:
            raise RuntimeError('Expected exactly one N90 erase identity')
        parts = choices[0]['Manifest']
        llb = parts['LLB']['Info']['Path']
        logo = parts['AppleLogo']['Info']['Path']
        if llb != 'Firmware/all_flash/all_flash.n90ap.production/LLB.n90ap.RELEASE.img3':
            raise RuntimeError('Unexpected LLB member path')
        replacement = archive.read(logo)
        original_entries = {i.filename: (i.CRC, i.file_size) for i in archive.infolist()}
    staged = WORK / llb
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_bytes(replacement)
    destination = WORK / 'iPhone3,1_7.1.2_11D257_DFU.ipsw'
    shutil.copyfile(SOURCE, destination)
    sp.run(['zip', '-q', '-0', str(destination), llb], cwd=WORK, check=True, timeout=120)
    with zipfile.ZipFile(destination) as archive:
        entries = archive.infolist()
        if len(entries) != len({i.filename for i in entries}):
            raise RuntimeError('Duplicate ZIP members')
        modified = {i.filename: (i.CRC, i.file_size) for i in entries}
        if set(modified) != set(original_entries):
            raise RuntimeError('Archive member list changed')
        if [n for n in modified if modified[n] != original_entries[n]] != [llb]:
            raise RuntimeError('Changes exceed the single upstream LLB replacement')
        if archive.read(llb) != replacement:
            raise RuntimeError('LLB replacement verification failed')
    with destination.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    (WORK / 'artifact.json').write_text(json.dumps({
        'upstream_revision': REV, 'source_sha256': SOURCE_SHA,
        'modified_sha256': digest, 'changed_member': llb,
        'replacement_member': logo, 'scope': 'local Apple firmware; never publish'}, indent=2) + '\n')
    return destination


def report(text):
    # One terminal report only. Never retry an ambiguous Telegram send.
    import notify
    try:
        delivery = notify.send(text)
        (WORK / 'notification.json').write_text(json.dumps({'state': 'delivered', 'id': delivery}) + '\n')
    except Exception as exc:
        (WORK / 'notification.json').write_text(json.dumps({'state': 'delivery_unconfirmed', 'reason': type(exc).__name__}) + '\n')


def release_to_kernel():
    cfg = json.loads((ROOT / '.runtime/settings.json').read_text())
    lane = next(w for w in cfg['workers'] if w['name'] == 'kernel')
    path = Path(lane['path']) / '.opencode/review-feedback.json'
    feedback = json.loads(path.read_text())
    feedback.update(id='master-dfu-release-' + str(int(time.time())), decision='continue')
    feedback['next_action'] = (
        'Master restore has ended and verified the pinned phone in DFU. You now own the phone USB connection for one bounded RAM-boot attempt; this supersedes the temporary master ownership hold in goals/reliability.md. First verify /seed/handoff/software-boot-status.json is dfu_verified or dfu_already_present and recheck live pinned ECID/model. Use /seed/handoff/recovery-knownboot-20261021/manifest.json and its exact hash-verified original boot files, including the preserved fixed loader. No other lane may operate USB. Do not flash NAND or modify host services. Boot through openiBoot and confirm actual Linux USB enumeration, capture private raw evidence, then stop for master identity restoration and idle deployment. The saved SSH/Tailscale private state remains master-only; never bypass host-key checks or re-enroll. If a loader stage fails, retain logs and report its exact first failed stage instead of looping. Continue the offline reliability work afterward. Prior review context: '
        + feedback.get('next_action', ''))
    temporary = path.with_suffix('.new')
    temporary.write_text(json.dumps(feedback, indent=2) + '\n')
    temporary.replace(path)


def main():
    os.umask(0o077)
    WORK.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (WORK / 'restore-started.json').exists():
        raise RuntimeError('This one-shot restore has already been attempted; inspect evidence before retrying')
    status('waiting_for_verified_download')
    deadline = time.monotonic() + 2700
    while not SOURCE.exists():
        if time.monotonic() > deadline:
            raise RuntimeError('Firmware download did not finish before the deadline')
        time.sleep(10)
    verify_tools()
    mode, ecid = identity()
    if mode == 'dfu':
        status('dfu_already_present', linux_booted=False)
        release_to_kernel()
        return
    if mode != 'recovery':
        raise RuntimeError('Restore requires the pinned phone in recovery mode')
    status('preparing_verified_dfu_image')
    artifact = prepare()
    mode, current_ecid = identity()
    if mode != 'recovery' or current_ecid != ecid:
        raise RuntimeError('Phone identity/mode changed during image preparation')
    (WORK / 'restore-started.json').write_text(json.dumps({'started_at': time.time(), 'target': 'pinned N90AP'}) + '\n')
    status('restoring_dfu_image', linux_booted=False)
    env = dict(os.environ, LD_LIBRARY_PATH=str(KIT / 'lib'))
    (WORK / 'restore-cache').mkdir(exist_ok=True)
    with (WORK / 'restore.log').open('wb') as log:
        result = sp.run([str(KIT / 'idevicerestore'), '-e', '-y', '-i', ecid,
                         '-C', str(WORK / 'restore-cache'), str(artifact)],
                        cwd=WORK, env=env, stdout=log, stderr=sp.STDOUT, timeout=1200)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            mode, observed_ecid = identity()
            if mode == 'dfu' and observed_ecid == ecid:
                status('dfu_verified', restore_exit=result.returncode, linux_booted=False)
                release_to_kernel()
                report('SoyOs: the button-free firmware procedure reached verified DFU on your iPhone 4. No button sequence was needed. Linux has not been reloaded yet; the next step is the automatic boot and identity-restore path. Evidence is saved privately on Platt.')
                return
        except (OSError, RuntimeError):
            pass
        time.sleep(3)
    status('restore_did_not_reach_dfu', restore_exit=result.returncode, linux_booted=False)
    report('SoyOs: the button-free DFU restore attempt did not reach verified DFU. It has stopped without automatic retries. The maintainer needs to review the private restore log; no more button attempts are requested.')
    raise SystemExit(1)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        status('stopped', error_type=type(exc).__name__, linux_booted=False)
        # Exception text and device output stay private.
        (WORK / 'error.txt').write_text(str(exc) + '\n')
        report('SoyOs: preparation for the button-free DFU restore stopped. No automatic retry will run. The maintainer needs to inspect its private status and error on Platt; you do not need to repeat the button sequence.')
        raise SystemExit(1)
