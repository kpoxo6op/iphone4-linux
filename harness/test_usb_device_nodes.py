"""Wrong-device and re-enumeration boundaries need host tests, not QEMU."""
import hashlib
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

import usb_device_nodes as usb


class DeviceScope(unittest.TestCase):
    def setUp(self):
        self.policy = {'devpath': '/devices/usb3/3-4',
                       'ecid_sha256': hashlib.sha256(b'12345').hexdigest(),
                       'uid': 1000, 'gid': 1000}

    def test_only_pinned_phone_or_its_loader_on_the_same_socket_matches(self):
        p = self.policy
        self.assertTrue(usb.matches(p, p['devpath'], '05ac', '1281', 'ECID:00003039'))
        self.assertTrue(usb.matches(p, p['devpath'], '05ac', '1227', 'ECID:3039'))
        self.assertFalse(usb.matches(p, p['devpath'], '05ac', '1227', 'ECID:3040'))
        self.assertFalse(usb.matches(p, '/devices/usb3/3-5', '05ac', '1227', 'ECID:3039'))
        self.assertFalse(usb.matches(p, p['devpath'], '05ac', '1281', ''))
        self.assertTrue(usb.matches(p, p['devpath'], '0525', '1280', ''))
        self.assertTrue(usb.matches(p, p['devpath'], '0525', 'a4a2', ''))
        self.assertFalse(usb.matches(p, '/devices/usb3/3-5', '0525', 'a4a2', ''))
        self.assertFalse(usb.matches(p, p['devpath'], '18d1', '4ee7', ''))

    def test_replacement_revokes_old_node_and_late_remove_leaves_new_node(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'sys/devices/usb3/3-4'
            source.mkdir(parents=True)
            for key, val in {'idVendor': '05ac', 'idProduct': '1227',
                             'serial': 'ECID:3039', 'dev': '189:326'}.items():
                (source / key).write_text(val)
            nodes = root / 'nodes'
            (nodes / '003').mkdir(parents=True)
            (nodes / '003/070').touch()
            env = {'DEVPATH': self.policy['devpath'], 'BUSNUM': '3',
                   'DEVNUM': '71', 'ACTION': 'add'}
            # Real directory lifecycle; no root/device creation in the test.
            with patch.object(usb.os, 'mknod', side_effect=lambda p, *_: p.touch()), \
                 patch.object(usb.os, 'chown'):
                usb.update(self.policy, env, root / 'sys', nodes)
            self.assertFalse((nodes / '003/070').exists())
            self.assertTrue((nodes / '003/071').exists())
            usb.update(self.policy, dict(env, ACTION='remove', DEVNUM='70'), root / 'sys', nodes)
            self.assertTrue((nodes / '003/071').exists())
            (source / 'serial').write_text('ECID:3040')
            usb.update(self.policy, env, root / 'sys', nodes)
            self.assertEqual(list(nodes.glob('*/*')), [])


if __name__ == '__main__':
    unittest.main()
