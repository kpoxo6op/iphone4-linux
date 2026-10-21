#!/usr/bin/env python3
"""Extract the N90 touch firmware from the iPhone3,1 iOS 7.1.2 restore IPSW.

The root filesystem DMG (058-4520-010.dmg) is FileVault-encrypted. Its key is
public: https://api.ipsw.me/v4/keys/ipsw/iPhone3,1/11D257 ("RootFS").
The firmware is Apple's; keep the output private and out of Git.

usage: extract_firmware.py IPSW OUT.bin   (needs 7z and python3-cryptography)
"""
import hashlib, hmac, plistlib, struct, subprocess, sys, tempfile, zipfile
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ROOTFS = '058-4520-010.dmg'
KEY = bytes.fromhex('38d0320d099b9dd34ffb3308c53d397f14955b347d6a433fe173acc2ced1ae78756b3684')
MTPROPS = 'Sochi11D257.N90OS/usr/share/firmware/multitouch/N90.mtprops'
SHA256 = '359b6154c8aaffb22eb6e9350be7c718be0bf00fbddbac257e9d10582e62428f'


def vfdecrypt(src, dst):
    aes, mac = KEY[:16], KEY[16:]
    with open(src, 'rb') as f, open(dst, 'wb') as out:
        h = f.read(0x100)
        assert h[:8] == b'encrcdsa', 'not an encrypted DMG'
        bs, = struct.unpack('>I', h[52:56])
        size, off = struct.unpack('>QQ', h[56:72])
        f.seek(off)
        for i in range(0, (size + bs - 1) // bs):
            iv = hmac.new(mac, struct.pack('>I', i), hashlib.sha1).digest()[:16]
            chunk = Cipher(algorithms.AES(aes), modes.CBC(iv)).decryptor().update(f.read(bs))
            out.write(chunk[:min(bs, size - i * bs)])


def main():
    ipsw, out = Path(sys.argv[1]), Path(sys.argv[2])
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        with zipfile.ZipFile(ipsw) as z:
            z.extract(ROOTFS, tmp)
        vfdecrypt(tmp / ROOTFS, tmp / 'rootfs.dmg')
        subprocess.run(['7z', 'e', '-y', f'-o{tmp}', str(tmp / 'rootfs.dmg'), MTPROPS],
                       check=True, capture_output=True)
        props = plistlib.loads((tmp / 'N90.mtprops').read_bytes())['N1F55,1']
    fw = props['Constructed Firmware']
    digest = hashlib.sha256(fw).hexdigest()
    if digest != SHA256:
        raise SystemExit(f'unexpected firmware {digest}')
    out.write_bytes(fw)
    print(f'{out}: {len(fw)} bytes, version {props["Constructed Firmware Version"]}')


if __name__ == '__main__':
    main()
