"""Host recovery orchestration; a guest boot cannot cover pinned-host SSH policy."""
import json
from pathlib import Path
import subprocess as sp
import tempfile
import unittest
from unittest.mock import patch

import phone_reconnect


class Reconnect(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lost = {'status': 'no_device', 'last_linux_usb_at': '2026-10-20T19:41:44Z',
                     'observed_since': '2026-10-20T19:42:15Z'}
        self.live = {**self.lost, 'status': 'linux_usb',
                     'identity': {'HardwareModel': 'N90AP'}}

    def state(self):
        return json.loads((self.root / 'private/reconnect.json').read_text())

    def test_absent_or_unidentified_phone_never_receives_ssh(self):
        # A stale or unrelated USB arrival must not become a remote target.
        with patch.object(phone_reconnect.sp, 'run') as run:
            phone_reconnect.check({'status': 'no_device'}, self.root)
            phone_reconnect.check(self.lost, self.root)
            phone_reconnect.check({**self.live, 'identity': {}}, self.root)
        run.assert_not_called()
        self.assertEqual(self.state()['state'], 'waiting_usb')

    def test_failed_authentication_keeps_recovery_pending_without_trust_bypass(self):
        phone_reconnect.check(self.lost, self.root)
        with patch.object(phone_reconnect.sp, 'run', return_value=sp.CompletedProcess(
                [], 255, b'', b'private endpoint details')) as run:
            phone_reconnect.check(self.live, self.root)
        self.assertIn('StrictHostKeyChecking=yes', run.call_args.args[0])
        self.assertEqual(self.state()['state'], 'waiting_ssh')
        self.assertNotIn('private endpoint', json.dumps(self.state()))

    def test_verified_return_saves_private_evidence_once_and_checks_same_boot(self):
        # Repeated timer ticks must not keep opening sessions or claim a
        # different tailnet boot as the USB session that was just verified.
        boot = b'00000000-0000-4000-8000-000000000001\n'
        for tailnet in (boot, b'00000000-0000-4000-8000-000000000002\n'):
            phone_reconnect.check(self.lost, self.root)
            with patch.object(phone_reconnect.sp, 'run', side_effect=[
                    sp.CompletedProcess([], 0, boot + b'kernel diagnostics\n', b''),
                    sp.CompletedProcess([], 0, tailnet, b'')]) as run:
                phone_reconnect.check(self.live, self.root)
                phone_reconnect.check(self.live, self.root)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(self.state()['state'], 'recovered')
            self.assertEqual(self.state()['tailnet_same_boot'], tailnet == boot)
            log = self.root / 'private/reconnect-diagnostics.txt'
            self.assertEqual(log.stat().st_mode & 0o777, 0o600)
            self.assertIn(b'kernel diagnostics', log.read_bytes())


if __name__ == '__main__':
    unittest.main()
