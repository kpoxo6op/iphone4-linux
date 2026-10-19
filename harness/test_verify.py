"""Receipt boundaries not covered by the guest boot/SSH acceptance test."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import verify


class EvidenceBoundary(unittest.TestCase):
    def test_missing_images_do_not_reuse_a_previous_pass(self):
        """A failed new attempt must retain a distinct failure receipt."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = root / 'prior-result.json'
            old.write_text('{"passed": true}')
            result = subprocess.run([sys.executable, verify.__file__, 'qemu',
                                    '--images', str(root / 'missing'),
                                    '--results', str(root / 'runs')],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            receipt = Path(json.loads(result.stdout)['receipt'])
            data = json.loads(receipt.read_text())
            self.assertFalse(data['passed'])
            self.assertEqual(set(data['doctor']['missing_images']), set(verify.IMAGES))
            self.assertNotIn('command', data)
            self.assertTrue(old.exists())
            self.assertFalse((receipt.parent / 'images').exists())

    def test_doctor_tracks_actual_bytes_without_claiming_boot(self):
        """A rebuild changes input identity; readiness alone is never proof."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in verify.IMAGES:
                (root / name).write_bytes(b'fixture, not a bootable image')
            before = verify.doctor(root)
            (root / 'zImage').write_bytes(b'changed fixture')
            after = verify.doctor(root)
            self.assertNotEqual(before['sha256']['zImage'], after['sha256']['zImage'])
            self.assertNotIn('passed', after)
            self.assertEqual(before['sha256']['rootfs.ext4'], after['sha256']['rootfs.ext4'])


if __name__ == '__main__':
    unittest.main()
